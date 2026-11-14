#pragma once
#ifdef STUDY_SD_ONLY
#include "deployment_build.h"
// Network work never runs on the UI loop.
#include "fleet_client.h"
#include "card_art.h"
#include "local_bank_assets.h"
#include "navigation_art_assets.h"
#include "home_zoom_assets.h"
#include "overlay_assets.h"
#include "esp_ota_ops.h"
#include "mbedtls/aes.h"
#include "artifact_retention.h"
#include <atomic>
#include <sys/stat.h>

namespace p4_runtime {
class Deployment {
  TaskHandle_t task_{};
  std::atomic<bool> healthy_{false},idle_{false},reboot_{false};
  bool confirmed_=false;
  int64_t boot_=esp_timer_get_time(),healthy_since_=0;
  uint32_t highest_=STUDY_BUILD_GENERATION;
  ArtifactRetention retention_;
  const FleetSettings &settings_;
  struct File {std::string hash,role;size_t bytes=0;uint8_t digest[32]{};};
  bool persist(uint32_t generation){
    nvs_handle_t h;
    if(nvs_open("p4-update",NVS_READWRITE,&h)!=ESP_OK)return false;
    bool ok=nvs_set_u32(h,"attempt",generation)==ESP_OK && nvs_commit(h)==ESP_OK;
    nvs_close(h);if(ok)highest_=generation;return ok;
  }
  static bool parse(const cJSON *item,File &file){
    file.hash=field(item,"sha256");file.role=field(item,"role");
    const auto *length=cJSON_GetObjectItemCaseSensitive(item,"bytes");
    if(file.hash.size()!=64 || !cJSON_IsNumber(length) || length->valuedouble!=length->valueint || length->valueint<=0 || length->valueint>160*1024*1024)return false;
    file.bytes=length->valueint;
    for(unsigned i=0;i<64;++i){char c=file.hash[i];if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
      file.digest[i/2]=(file.digest[i/2]<<4)|(c<='9'?c-'0':c-'a'+10);}
    return true;
  }
  bool verified(const std::string &path,const File &file){
    study::CardArt card;
    if(!card.mount())return false;
    const int input=::open(path.c_str(),O_RDONLY);if(input<0)return false;
    struct stat info{};
    bool ok=fstat(input,&info)==0 && info.st_size==off_t(file.bytes);
    // The three live artwork readers already hold DMA buffers. Verification
    // needs a sequential hash, so do not reserve another scarce DMA buffer.
    auto *buffer=static_cast<uint8_t*>(heap_caps_malloc(8192,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    mbedtls_sha256_context sha;mbedtls_sha256_init(&sha);
    ok=ok && buffer && mbedtls_sha256_starts(&sha,0)==0;
    for(size_t n=0;ok && n<file.bytes;){
      if(!idle_){ok=false;break;}
      const size_t count=std::min(size_t(8192),file.bytes-n);
      ok=::read(input,buffer,count)==ssize_t(count) && mbedtls_sha256_update(&sha,buffer,count)==0;
      n+=count;vTaskDelay(1);
    }
    uint8_t actual[32]{};
    ok=ok && mbedtls_sha256_finish(&sha,actual)==0 && !memcmp(actual,file.digest,32);
    mbedtls_sha256_free(&sha);heap_caps_free(buffer);::close(input);return ok;
  }
  void report(uint32_t generation,const char *state,const char *detail){
    Json body(cJSON_CreateObject(),cJSON_Delete);
    cJSON_AddNumberToObject(body.get(),"generation",generation);
    cJSON_AddStringToObject(body.get(),"state",state);cJSON_AddStringToObject(body.get(),"detail",detail);
    char *encoded=cJSON_PrintUnformatted(body.get());
    if(encoded){request(settings_,"/api/p4/"+std::string(settings_.id)+"/report",encoded);cJSON_free(encoded);}
  }
  bool download(uint32_t generation,const File &file){
    const std::string root="/sd/pi-panel/",target=root+file.hash+".bin",partial=root+file.hash+".part";
    if(verified(target,file))return true;
    if(!idle_)return false;
    study::CardArt card;uint64_t total=0,free=0;
    if(!card.mount() || !card.space(total,free))return false;
    mkdir(root.c_str(),0700);
    struct stat st{};size_t offset=0;
    if(stat(partial.c_str(),&st)==0 && st.st_size>=0 && size_t(st.st_size)<=file.bytes)offset=st.st_size;
    // Resume after power loss between the final write and atomic promotion.
    if(offset==file.bytes){
      if(verified(partial,file))return rename(partial.c_str(),target.c_str())==0;
      if(!idle_)return false;
      remove(partial.c_str());offset=0;
    }
    if(free<file.bytes-offset+2*1024*1024)return false;
    const std::string url=std::string(settings_.url)+"/api/p4/"+settings_.id+"/files/"+std::to_string(generation)+"/"+file.hash;
    esp_http_client_config_t cfg{};cfg.url=url.c_str();cfg.timeout_ms=10000;cfg.disable_auto_redirect=true;
    cfg.crt_bundle_attach=esp_crt_bundle_attach;
    auto client=esp_http_client_init(&cfg);if(!client)return false;
    esp_http_client_set_header(client,"X-Panel-Token",settings_.token);
    if(offset){const auto range="bytes="+std::to_string(offset)+"-";esp_http_client_set_header(client,"Range",range.c_str());}
    bool ok=esp_http_client_open(client,0)==ESP_OK;
    const int64_t length=ok?esp_http_client_fetch_headers(client):-1;
    const int status=esp_http_client_get_status_code(client);
    ESP_LOGI("p4_deploy","Downloading %s: HTTP %d, %lld bytes remaining",file.role.c_str(),status,length);
    // Older Starlette versions ignore Range. Restart the private partial file.
    if(offset && status==200)offset=0;
    ok=ok && (status==(offset?206:200)) && length==int64_t(file.bytes-offset);
    FILE *out=ok?fopen(partial.c_str(),offset?"ab":"wb"):nullptr;ok=ok && out;
    auto *buffer=static_cast<uint8_t*>(heap_caps_malloc(16384,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    ok=ok && buffer;
    const std::string context="p4-artifact-v1\n"+std::to_string(generation)+"\n"+file.hash;
    uint8_t key[32]{},counter[16]{},stream[16]{},skip[16]{};size_t used=0;
    mbedtls_aes_context aes;mbedtls_aes_init(&aes);
    ok=ok && mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
      reinterpret_cast<const uint8_t*>(settings_.sign_key),strlen(settings_.sign_key),
      reinterpret_cast<const uint8_t*>(context.data()),context.size(),key)==0 && mbedtls_aes_setkey_enc(&aes,key,256)==0;
    uint64_t block=offset/16;for(int i=15;i>=8;--i){counter[i]=block&255;block>>=8;}
    if(ok && offset%16)ok=mbedtls_aes_crypt_ctr(&aes,offset%16,&used,counter,stream,skip,skip)==0;
    memset(key,0,sizeof(key));
    while(ok && offset<file.bytes){
      if(!idle_){ok=false;break;} // yield SD bandwidth immediately to a person using the panel
      const int got=esp_http_client_read(client,reinterpret_cast<char*>(buffer),std::min(size_t(16384),file.bytes-offset));
      ok=got>0 && mbedtls_aes_crypt_ctr(&aes,got,&used,counter,stream,buffer,buffer)==0 && fwrite(buffer,1,got,out)==size_t(got);
      if(ok)offset+=got;
      vTaskDelay(pdMS_TO_TICKS(10));
    }
    if(out){ok=fflush(out)==0 && ok;ok=fsync(fileno(out))==0 && ok;fclose(out);}
    mbedtls_aes_free(&aes);
    heap_caps_free(buffer);esp_http_client_close(client);esp_http_client_cleanup(client);
    ok=ok && verified(partial,file);
    if(!ok)ESP_LOGW("p4_deploy","%s download paused or failed at %u/%u (errno %d)",file.role.c_str(),unsigned(offset),unsigned(file.bytes),errno);
    if(!ok && idle_ && offset==file.bytes)remove(partial.c_str()); // only this exact hash-named partial
    return ok && rename(partial.c_str(),target.c_str())==0;
  }
  bool install(const File &file){
    const auto *part=esp_ota_get_next_update_partition(nullptr);
    if(!part || file.bytes>part->size)return false;
    FILE *input=fopen(("/sd/pi-panel/"+file.hash+".bin").c_str(),"rb");if(!input)return false;
    auto *buffer=static_cast<uint8_t*>(heap_caps_malloc(16384,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    esp_ota_handle_t handle=0;
    bool ok=buffer && esp_ota_begin(part,file.bytes,&handle)==ESP_OK;
    for(size_t n=0;ok && n<file.bytes;){
      const size_t size=std::min(size_t(16384),file.bytes-n);
      ok=fread(buffer,1,size,input)==size && esp_ota_write(handle,buffer,size)==ESP_OK;
      n+=size;vTaskDelay(1);
    }
    fclose(input);heap_caps_free(buffer);
    if(!ok){if(handle)esp_ota_abort(handle);return false;}
    return esp_ota_end(handle)==ESP_OK && esp_ota_set_boot_partition(part)==ESP_OK;
  }
  void poll(){
    auto reply=request(settings_,"/api/p4/"+std::string(settings_.id)+"/release");
    if(reply.status!=200)return;
    auto manifest=verified_config(reply.body,reply.signature,settings_.sign_key,settings_.id);
    if(!manifest || strcmp(field(manifest.get(),"encryption"),"aes-256-ctr-signed-sha256-v1") ||
       strcmp(field(manifest.get(),"hardware"),"waveshare-p4-wifi6-32mb-5dsi-720x1280-v1") ||
       strcasecmp(field(manifest.get(),"mac"),settings_.mac))return;
    const auto *version=cJSON_GetObjectItemCaseSensitive(manifest.get(),"_version");
    if(version->valuedouble!=version->valueint || version->valueint<=0)return;
    const uint32_t generation=version->valueint;
    if(generation==STUDY_BUILD_GENERATION){report(generation,"installed","Local display and artwork healthy");return;}
    if(generation<=highest_){report(generation,"failed","Previous boot attempt rejected; retry requires a new build");return;}
    if(!idle_)return;
    File application;
    if(!parse(cJSON_GetObjectItemCaseSensitive(manifest.get(),"application"),application) || application.role!="application" || application.bytes>0x300000)return;
    auto *assets=cJSON_GetObjectItemCaseSensitive(manifest.get(),"artwork");
    if(!cJSON_IsArray(assets) || cJSON_GetArraySize(assets)!=6)return;
    std::vector<File> files;
    unsigned roles=0;
    for(const auto *item=assets->child;item;item=item->next){
      File f;if(!parse(item,f))return;
      unsigned bit=0;const char *names[]={"volume","text","palette","navigation","home","overlays"};
      for(unsigned i=0;i<6;++i)if(f.role==names[i])bit=1u<<i;
      if(!bit || roles&bit)return;roles|=bit;files.push_back(f);
    }
    report(generation,"staging","Downloading and verifying artwork");
    std::vector<const uint8_t*> incoming{application.digest};
    for(const auto &file:files)incoming.push_back(file.digest);
    if(!retention_.prepare(incoming,idle_)){
      report(generation,"staging","Waiting for idle card storage; both healthy artwork banks retained");return;
    }
    for(const auto &file:files)if(!download(generation,file)){
      report(generation,"staging","Artwork download interrupted, verification failed or card full; retrying");return;
    }
    if(!download(generation,application)){
      report(generation,"staging","Application download interrupted or card full; retrying");return;
    }
    // Do not start flash writes while someone is using the controls or camera.
    while(!idle_ || !healthy_)vTaskDelay(pdMS_TO_TICKS(1000));
    // Refresh the offer immediately before activation: an edited room supersedes it.
    const auto latest=request(settings_,"/api/p4/"+std::string(settings_.id)+"/release");
    if(latest.status!=200 || latest.body!=reply.body || latest.signature!=reply.signature)return;
    if(!persist(generation))return;
    report(generation,"installing","Installing verified application");
    if(!install(application)){report(generation,"failed","Application installation failed; prior slot retained");return;}
    reboot_=true;
  }
  static void worker(void *ptr){
    auto &self=*static_cast<Deployment*>(ptr);
    if(!self.retention_.boot({study::local_volume.sha,study::local_text.sha,study::local_palette.sha,
       study::sd_navigation_sha,study::home_zoom_sha,study::overlay_sha})){
      ESP_LOGE("p4_deploy","Cannot safely open artwork retention journal; automatic updates disabled");
      vTaskDelete(nullptr);return;
    }
    nvs_handle_t h;
    if(nvs_open("p4-update",NVS_READONLY,&h)==ESP_OK){uint32_t value=0;nvs_get_u32(h,"attempt",&value);self.highest_=std::max(self.highest_,value);nvs_close(h);}
    for(;;){if(self.healthy_ && esphome::network::is_connected())self.poll();vTaskDelay(pdMS_TO_TICKS(60000));}
  }
 public:
  explicit Deployment(const FleetSettings &settings):settings_(settings){}
  void tick(bool local_ok,bool idle){
    idle_=idle;
    const int64_t now=esp_timer_get_time();
    if(!local_ok)healthy_since_=0;
    else if(!healthy_since_)healthy_since_=now;
    if(!confirmed_ && healthy_since_ && now-healthy_since_>10000000){
      esp_ota_img_states_t state{};
      const auto *running=esp_ota_get_running_partition();
      const auto result=esp_ota_get_state_partition(running,&state);
      if(result==ESP_ERR_NOT_FOUND || (result==ESP_OK && state==ESP_OTA_IMG_UNDEFINED)){
        // USB bootstrap has no OTA selection record. Give this known-working
        // slot a verified boot entry before allowing any network update.
        if(esp_ota_set_boot_partition(running)!=ESP_OK)return;
        esphome::App.safe_reboot();return;
      }
      if(result!=ESP_OK)return;
      if(state==ESP_OTA_IMG_PENDING_VERIFY){
        if(esp_ota_mark_app_valid_cancel_rollback()!=ESP_OK)return;
      }
      if(state!=ESP_OTA_IMG_VALID && state!=ESP_OTA_IMG_PENDING_VERIFY)return;
      confirmed_=true;healthy_=true;
    }
    if(!confirmed_ && now-boot_>180000000){esp_ota_mark_app_invalid_rollback_and_reboot();return;}
    if(confirmed_ && !task_)xTaskCreate(worker,"p4_deploy",12288,this,1,&task_);
    if(reboot_)esphome::App.safe_reboot();
  }
};
}
#endif
