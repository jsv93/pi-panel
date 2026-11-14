#pragma once
#include "config_store.h"
#include <esp_websocket_client.h>
#include <esp_crt_bundle.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace p4_runtime {
// Outbound connection to the provisioned server, using the device's enrollment
// token. Only the fixed panel actions are accepted, on the main rendering loop.
class FleetSocket {
 public:
  enum class Action { none, identify, wake, sleep, reload, restart };
  void begin(const char *server,const char *id,const char *token){
    if(client_)return;
    uri_=server;
    if(uri_.compare(0,8,"https://")==0)uri_.replace(0,8,"wss://");
    else if(uri_.compare(0,7,"http://")==0)uri_.replace(0,7,"ws://");
    else return;
    uri_+="/api/ws/";uri_+=id;
    headers_=std::string("X-Panel-Token: ")+token+"\r\n";
    if(!actions_)actions_=xQueueCreate(8,sizeof(Action));
    if(!actions_)return;
    esp_websocket_client_config_t config{};
    config.uri=uri_.c_str();config.headers=headers_.c_str();
    config.crt_bundle_attach=esp_crt_bundle_attach;
    config.task_stack=6144;config.task_prio=1;config.buffer_size=1024;
    config.reconnect_timeout_ms=5000;config.network_timeout_ms=4000;
    config.ping_interval_sec=10;config.pingpong_timeout_sec=15;
    client_=esp_websocket_client_init(&config);
    if(!client_)return;
    esp_websocket_register_events(client_,WEBSOCKET_EVENT_ANY,event,this);
    if(esp_websocket_client_start(client_)!=ESP_OK)finished_=true;
  }
  void maintain(){
    // A clean server shutdown ends the library's worker. Restart it from our
    // fleet task, outside the WebSocket event callback.
    if(finished_.exchange(false) && client_ && esp_websocket_client_start(client_)!=ESP_OK)finished_=true;
  }
  bool send(const std::string &message){
    return client_ && esp_websocket_client_is_connected(client_) &&
      esp_websocket_client_send_text(client_,message.data(),message.size(),pdMS_TO_TICKS(1000))==int(message.size());
  }
  Action take_action(){
    Action action=Action::none;
    if(auto queue=actions_.load())xQueueReceive(queue,&action,0);
    return action;
  }
  bool take_sync(){return sync_.exchange(false);}
 private:
  esp_websocket_client_handle_t client_{};
  std::atomic<QueueHandle_t> actions_{nullptr};
  std::string uri_,headers_,incoming_;
  std::atomic<bool> finished_{false},sync_{false};
  static void event(void *arg,esp_event_base_t,int32_t id,void *data){
    static_cast<FleetSocket*>(arg)->receive(id,static_cast<esp_websocket_event_data_t*>(data));
  }
  void receive(int32_t id,const esp_websocket_event_data_t *data){
    if(id==WEBSOCKET_EVENT_FINISH){finished_=true;return;}
    if(id==WEBSOCKET_EVENT_DISCONNECTED || id==WEBSOCKET_EVENT_CLOSED){
      incoming_.clear();if(auto queue=actions_.load())xQueueReset(queue);return;
    }
    if(id!=WEBSOCKET_EVENT_DATA || data->op_code!=1)return;
    if(data->payload_offset==0)incoming_.clear();
    if(data->payload_len<0 || data->payload_len>2048 || data->data_len<0 ||
       data->payload_offset!=int(incoming_.size()) || data->data_len>data->payload_len-data->payload_offset){incoming_.clear();return;}
    incoming_.append(data->data_ptr,data->data_len);
    if(int(incoming_.size())!=data->payload_len)return;
    Json doc(cJSON_Parse(incoming_.c_str()),cJSON_Delete);
    if(!doc)return;
    const std::string type=field(doc.get(),"type");
    if(type=="config" || type=="config_updated" || type=="sync"){sync_=true;return;}
    Action action=Action::none;
    if(type=="identify")action=Action::identify;
    else if(type=="wake")action=Action::wake;
    else if(type=="sleep")action=Action::sleep;
    else if(type=="reload"){sync_=true;action=Action::reload;}
    else if(type=="restart")action=Action::restart;
    if(action!=Action::none && xQueueSend(actions_.load(),&action,0)==pdTRUE)
      ESP_LOGI("p4_fleet","Server action %s",type.c_str());
  }
};
}
