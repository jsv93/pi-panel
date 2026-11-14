#pragma once
#include "fleet_client.h"
#include <lwip/netdb.h>
#include <lwip/inet.h>
#include <esp_heap_caps.h>
#include <array>
#include <mbedtls/sha256.h>

extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);

namespace p4_runtime {
class AlbumClient {
 public:
  struct Frame {uint8_t *data=nullptr;size_t size=0;uint32_t version=0;};
  static constexpr size_t limit=384*1024;
  uint32_t generation()const{return generation_;}
  bool initialized()const{return jobs_ && result_;}
  void start(const char *origin,bool library_thumbnails=false,const FleetSettings *fleet=nullptr){
    origin_=origin;
    thumbnails_=library_thumbnails;
    fleet_=fleet;
    if(!*origin)return;
    jobs_=xQueueCreate(1,sizeof(Job));result_=xQueueCreate(1,sizeof(Frame));
  }
  void select(const char *entity,const std::string &value,bool force=false){
    if(!jobs_ || !result_ || (!force && entity==last_entity_ && value==last_))return;
    last_entity_=entity;
    const uint32_t version=++generation_;
    Job job{};job.version=version;job.entity=entity;
    last_=value;
    if(value.size()<sizeof(job.url))memcpy(job.url,value.data(),value.size());
    xQueueOverwrite(jobs_,&job);
    if(!worker_)xTaskCreate([](void *p){static_cast<AlbumClient*>(p)->run();},"study_art",8192,this,1,&worker_);
  }
  bool take(Frame &f){return result_ && xQueueReceive(result_,&f,0)==pdTRUE;}
 private:
  struct Job {uint32_t version;const char *entity;char url[1536];};
  std::atomic<uint32_t> generation_{0};
  bool thumbnails_=false;
  const FleetSettings *fleet_=nullptr;
  const char *last_entity_="",*origin_="";
  std::string last_;
  QueueHandle_t jobs_{},result_{};
  TaskHandle_t worker_{};
  static std::string brand_path(const std::string &picture){
    const std::string prefix="/api/brands/integration/";
    if(picture.compare(0,prefix.size(),prefix))return {};
    const auto path=picture.substr(prefix.size());
    const auto slash=path.find('/');
    if(slash==0 || slash>100 || path.substr(0,slash).find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos)return {};
    const auto name=path.substr(slash+1);
    for(const char *image:{"icon.png","logo.png","icon@2x.png","logo@2x.png",
                           "dark_icon.png","dark_logo.png","dark_icon@2x.png","dark_logo@2x.png"})
      if(name==image)return path;
    return {};
  }
  std::array<uint8_t,32> cache_id(const Job &job)const{
    std::array<uint8_t,32> result{};
    const std::string key=std::string(origin_)+job.url;
    mbedtls_sha256(reinterpret_cast<const uint8_t*>(key.data()),key.size(),result.data(),0);
    return result;
  }
  bool cached_brand(const Job &job,Frame &frame)const{
    nvs_handle_t handle;
    if(nvs_open("panel-artwork",NVS_READONLY,&handle)!=ESP_OK)return false;
    const auto digest=cache_id(job);
    for(int slot=0;slot<12 && !frame.data;++slot){
      char key[8];snprintf(key,sizeof(key),"image%d",slot);
      size_t bytes=0;
      if(nvs_get_blob(handle,key,nullptr,&bytes)!=ESP_OK || bytes<40 || bytes>32+16384)continue;
      auto *record=static_cast<uint8_t*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!record)break;
      if(nvs_get_blob(handle,key,record,&bytes)==ESP_OK && !memcmp(record,digest.data(),32)){
        memmove(record,record+32,bytes-32);frame.data=record;frame.size=bytes-32;
      }else heap_caps_free(record);
    }
    nvs_close(handle);
    if(frame.data)ESP_LOGD("study","Provider artwork restored from local cache");
    return frame.data;
  }
  void cache_brand(const Job &job,const Frame &frame)const{
    nvs_handle_t handle;
    if(nvs_open("panel-artwork",NVS_READWRITE,&handle)!=ESP_OK)return;
    uint8_t next=0;nvs_get_u8(handle,"next",&next);
    char key[8];snprintf(key,sizeof(key),"image%d",next%12);
    auto *record=static_cast<uint8_t*>(heap_caps_malloc(32+frame.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(record){
      const auto digest=cache_id(job);
      memcpy(record,digest.data(),32);memcpy(record+32,frame.data,frame.size);
      // Identity and pixels share one atomic NVS blob. A reset while updating
      // the eviction cursor cannot associate an old image with a new URL.
      if(nvs_set_blob(handle,key,record,32+frame.size)==ESP_OK){
        nvs_set_u8(handle,"next",(next+1)%12);nvs_commit(handle);
      }
      heap_caps_free(record);
    }
    nvs_close(handle);
  }
  static bool valid_brand(const Frame &frame){
    if(!frame.data || frame.size<8 || frame.size>16384 || memcmp(frame.data,"P4RA",4))return false;
    constexpr size_t bytes=96*96*4;
    auto *decoded=heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    const bool ok=decoded && tinfl_decompress_mem_to_mem(decoded,bytes,frame.data+4,frame.size-4,1)==bytes;
    heap_caps_free(decoded);return ok;
  }
  static std::string host(const std::string &url){
    const size_t offset=url.compare(0,8,"https://")==0?8:url.compare(0,7,"http://")==0?7:0;
    if(!offset)return {};
    const auto end=url.find_first_of("/?#",offset);
    const auto authority=url.substr(offset,end-offset);
    if(authority.empty() || authority.find('@')!=std::string::npos)return {};
    const auto port=authority.find(':');
    if(port!=std::string::npos && (port+1==authority.size() ||
       authority.find_first_not_of("0123456789",port+1)!=std::string::npos))return {};
    const auto name=authority.substr(0,port);
    return name.find_first_not_of("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-")==std::string::npos?name:"";
  }
  std::string local_picture(const std::string &url)const{
    const size_t scheme=url.find("://");
    const size_t path=scheme==std::string::npos?std::string::npos:url.find('/',scheme+3);
    if(path==std::string::npos || url.compare(path,12,"/imageproxy/")!=0)return url;
    // Music Assistant accepts a discrete set of sizes. Its inspected
    // image URLs contain only size and format options, including size=0
    // for an unbounded original. Leave signed and unknown queries intact.
    const size_t query=url.find('?',path);
    if(query==std::string::npos)return url;
    for(size_t start=query+1;start<=url.size();){
      const size_t end=url.find('&',start);
      const auto pair=url.substr(start,end-start);
      if(pair.compare(0,5,"size=")!=0 && pair.compare(0,4,"fmt=")!=0)return url;
      if(end==std::string::npos)break;
      start=end+1;
    }
    return url.substr(0,query)+(thumbnails_?"?size=160&fmt=jpg":"?size=512&fmt=jpg");
  }
  std::string trusted_url(std::string picture,const char *entity)const{
    if(picture.find_first_of("\r\n\\#")!=std::string::npos)return {};
    const std::string proxy="/api/media_player_proxy/"+std::string(entity)+"?";
    if(picture.compare(0,proxy.size(),proxy)==0)return std::string(origin_)+picture;
    const auto source=host(picture),ha=host(origin_);
    if(source.empty() || ha.empty())return {};
    // HA supplies absolute HTTPS media thumbnails. This client sends no
    // credentials, rejects redirects and verifies the server certificate.
    if(source==ha)return local_picture(picture);
    if(thumbnails_ && picture.rfind("https://",0)==0)return picture;
    // HA may advertise its numeric LAN address for the Music Assistant image
    // service while the panel uses its mDNS name. Never attach a fleet token.
    struct in_addr ip{};
    if(inet_pton(AF_INET,source.c_str(),&ip)!=1)return {};
    addrinfo hints{},*addresses=nullptr;hints.ai_family=AF_INET;
    if(getaddrinfo(ha.c_str(),nullptr,&hints,&addresses))return {};
    bool same=false;
    for(auto *a=addresses;a;a=a->ai_next)
      if(reinterpret_cast<sockaddr_in*>(a->ai_addr)->sin_addr.s_addr==ip.s_addr)same=true;
    freeaddrinfo(addresses);return same?local_picture(picture):std::string{};
  }
  Frame fetch(const Job &job){
    Frame f{};f.version=job.version;
    const auto brand=thumbnails_?brand_path(job.url):std::string{};
    if(!brand.empty() && cached_brand(job,f)){
      if(valid_brand(f))return f;
      heap_caps_free(f.data);f.data=nullptr;f.size=0;
    }
    const bool paired=!brand.empty() && fleet_;
    const auto url=paired?std::string(fleet_->url)+"/api/panel/"+fleet_->id+"/artwork/"+brand:trusted_url(job.url,job.entity);
    if(url.empty())return f;
    esp_http_client_config_t cfg{};cfg.url=url.c_str();cfg.timeout_ms=5000;
    cfg.disable_auto_redirect=true;cfg.crt_bundle_attach=esp_crt_bundle_attach;
    auto h=esp_http_client_init(&cfg);if(!h)return f;
    if(paired)esp_http_client_set_header(h,"X-Panel-Token",fleet_->token);
    if(esp_http_client_open(h,0)==ESP_OK){
      const auto bytes=esp_http_client_fetch_headers(h);
      if(esp_http_client_get_status_code(h)==200 && bytes>=0 && size_t(bytes)<=(paired?16384:limit)){
        const size_t capacity=bytes?size_t(bytes):(paired?16384:limit);
        f.data=static_cast<uint8_t*>(heap_caps_malloc(capacity,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
        while(f.data && f.size<capacity && generation_==job.version){
          int n=esp_http_client_read(h,reinterpret_cast<char*>(f.data)+f.size,std::min<size_t>(8192,capacity-f.size));
          if(n<=0)break;
          f.size+=n;
        }
        const bool complete=f.data && (!bytes || f.size==capacity) && generation_==job.version;
        const bool valid=complete && (paired?valid_brand(f):
          f.size>=4 && f.data[0]==255 && f.data[1]==216 && f.data[f.size-2]==255 && f.data[f.size-1]==217);
        if(!valid){heap_caps_free(f.data);f.data=nullptr;f.size=0;}
        else if(paired)cache_brand(job,f);
      }
    }
    esp_http_client_cleanup(h);return f;
  }
  void run(){
    Job job{};
    for(;;){
      xQueueReceive(jobs_,&job,portMAX_DELAY);
      auto frame=fetch(job);
      if(frame.version!=generation_){heap_caps_free(frame.data);continue;}
      Frame old;
      if(xQueueReceive(result_,&old,0)==pdTRUE)heap_caps_free(old.data);
      xQueueSend(result_,&frame,0);
    }
  }
};
}
