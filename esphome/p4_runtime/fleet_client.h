#pragma once
#include "config_store.h"
#include "esphome/components/network/util.h"
#include <esp_http_client.h>
#include <esp_crt_bundle.h>
#include <esp_log.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>

namespace p4_runtime {
struct Reply {std::string body,signature; bool failed=false; int status=0;};
inline esp_err_t receive_http(esp_http_client_event_t *event){
  auto &reply=*static_cast<Reply*>(event->user_data);
  if(event->event_id==HTTP_EVENT_ON_HEADER && !strcasecmp(event->header_key,"X-Panel-Signature")){
    if(strlen(event->header_value)!=64 || !reply.signature.empty())reply.failed=true;
    else reply.signature=event->header_value;
  }
  if(event->event_id==HTTP_EVENT_ON_DATA){
    if(event->data_len<0 || size_t(event->data_len)>config_limit-reply.body.size())reply.failed=true;
    if(!reply.failed)reply.body.append(static_cast<char*>(event->data),event->data_len);
  }
  return reply.failed?ESP_FAIL:ESP_OK;
}
struct FleetSettings {const char *url,*id,*mac,*hostname,*token,*sign_key;};
inline Reply request(const FleetSettings &s,const std::string &path,const std::string &post={}){
  Reply r;
  std::string url=std::string(s.url)+path;
  esp_http_client_config_t cfg{};
  cfg.url=url.c_str();cfg.timeout_ms=4000;cfg.disable_auto_redirect=true;
  cfg.crt_bundle_attach=esp_crt_bundle_attach;
  cfg.event_handler=receive_http;cfg.user_data=&r;
  auto handle=esp_http_client_init(&cfg);
  if(!handle)return r;
  esp_http_client_set_header(handle,"X-Panel-Token",s.token);
  if(post.empty())esp_http_client_set_header(handle,"Accept","application/vnd.pi-panel.config+json");
  else{
    esp_http_client_set_method(handle,HTTP_METHOD_POST);
    esp_http_client_set_header(handle,"Content-Type","application/json");
    esp_http_client_set_post_field(handle,post.data(),post.size());
  }
  if(esp_http_client_perform(handle)==ESP_OK && !r.failed)r.status=esp_http_client_get_status_code(handle);
  esp_http_client_cleanup(handle);
  return r;
}

// The HTTP request runs on a worker. The first usable boot profile is always
// local, so DNS, Ethernet and a stopped server cannot delay local controls.
template<typename Profile> class FleetClient {
 public:
  using Decode=bool(*)(const cJSON*,Profile&);
  void begin(FleetSettings settings,Decode decode,const Profile &seed) {
    settings_=settings;decode_=decode;active_=seed;
    auto cached=load_config(settings_.sign_key,settings_.id,last_signature_);
    if(cached && decode_(cached.get(),active_))ESP_LOGI("p4_fleet","Booted cached profile v%d",active_.version);
    else{active_=seed;last_signature_.clear();ESP_LOGI("p4_fleet","Booted provisioned profile");}
    latest_=xQueueCreate(1,sizeof(Profile));
    changes_=xQueueCreate(1,sizeof(Change));
  }
  const Profile &active()const{return active_;}
  bool online()const{return online_.load();}
  enum class Edit {membership,preset};
  bool submit(Edit edit,const std::string &body){
    if(!task_ || !changes_ || !online_ || pending_ || body.size()>=sizeof(Change::body))return false;
    Change c{};c.edit=edit;c.issued=xTaskGetTickCount();
    memcpy(c.body,body.c_str(),body.size()+1);
    if(xQueueSend(changes_,&c,0)!=pdTRUE)return false;
    pending_=true;xTaskNotifyGive(task_);return true;
  }
  int result(){
    const int status=result_.exchange(0);
    if(status)pending_=false;
    return status;
  }
  bool tick(bool ha_connected){
    ha_connected_.store(ha_connected);
    if(latest_ && !task_ && esphome::network::is_connected()){
      esphome::network::get_ip_addresses()[0].str_to(ip_);
      xTaskCreate(worker,"p4_fleet",12288,this,1,&task_);
    }
    return latest_ && xQueueReceive(latest_,&active_,0)==pdTRUE;
  }
 private:
  struct Change {Edit edit;TickType_t issued;char body[1536];};
  QueueHandle_t changes_{};
  std::atomic<bool> online_{false};
  std::atomic<int> result_{0};
  bool pending_=false;
  FleetSettings settings_{};
  Decode decode_{};
  Profile active_{};
  QueueHandle_t latest_{};
  TaskHandle_t task_{};
  std::atomic<bool> ha_connected_{false};
  char ip_[48]{};
  std::string last_signature_;
  static void worker(void *ptr){static_cast<FleetClient*>(ptr)->run();}
  void run(){
    bool registered=false;
    int version=active_.version;
    for(;;){
      int edited_version=0;
      Change c{};
      if(changes_ && xQueueReceive(changes_,&c,0)==pdTRUE){
        if(registered && xTaskGetTickCount()-c.issued<pdMS_TO_TICKS(4000)){
          auto r=request(settings_,"/api/panel/"+std::string(settings_.id)+
              (c.edit==Edit::preset?"/presets":"/light"),c.body);
          Json ack(cJSON_Parse(r.body.c_str()),cJSON_Delete);
          auto *v=ack?cJSON_GetObjectItemCaseSensitive(ack.get(),"version"):nullptr;
          if(r.status==200 && cJSON_IsNumber(v))edited_version=v->valueint;
        }
        if(!edited_version)result_=-1;
      }
      if(!registered){
        // This client deliberately requires enrollment from the provisioning
        // host. The signing key never appears in a recurring network request.
        const std::string identity=std::string("{\"panel_id\":\"")+settings_.id+"\",\"hostname\":\""+
          settings_.hostname+"\",\"mac\":\""+settings_.mac+"\",\"ip\":\""+ip_+
          "\",\"kind\":\"esp\",\"version\":\"p4-candidate\"}";
        auto r=request(settings_,"/api/register",identity);
        Json answer(cJSON_Parse(r.body.c_str()),cJSON_Delete);
        registered=r.status==200 && answer && !strcmp(field(answer.get(),"token"),"active");
      }
      if(registered){
        const std::string heartbeat=std::string("{\"panel_id\":\"")+settings_.id+
          "\",\"config_version\":"+std::to_string(version)+",\"metrics\":{\"ha_connected\":"+
          (ha_connected_.load()?"true":"false")+"}}";
        auto h=request(settings_,"/api/heartbeat",heartbeat);
        online_=h.status==200;
        if(h.status==401 || h.status==404)registered=false;
        Json ack(cJSON_Parse(h.body.c_str()),cJSON_Delete);
        auto *want=ack?cJSON_GetObjectItemCaseSensitive(ack.get(),"config_version"):nullptr;
        if(h.status==200 && cJSON_IsNumber(want) && (want->valueint!=version || last_signature_.empty())){
          auto r=request(settings_,"/api/config/"+std::string(settings_.id));
          if(r.status==200 && r.signature.empty() && !unpack_legacy(r.body,r.signature)){
            ESP_LOGW("p4_fleet","Unsupported legacy signed configuration");
            r.status=0;
          }
          auto doc=verified_config(r.body,r.signature,settings_.sign_key,settings_.id);
          Profile next{};
          if(r.status==200 && doc && decode_(doc.get(),next) &&
             (last_signature_==r.signature || save_config(r.body,r.signature))){
            version=next.version;last_signature_=r.signature;xQueueOverwrite(latest_,&next);
            ESP_LOGI("p4_fleet","Cached signed profile v%d",version);
          }else ESP_LOGW("p4_fleet","Kept local profile; server configuration failed verification or layout checks");
        }
      }
      if(edited_version)result_=version>=edited_version?1:-1;
      ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(15000));
    }
  }
};
}
