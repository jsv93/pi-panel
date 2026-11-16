#pragma once
#include "esphome/components/api/api_server.h"
#include "esphome/components/api/api_connection.h"
#include <cstring>

namespace p4_runtime {
// ESPHome retains the const-char pointers. Each slot owns stable storage and
// registers once, so repeated server edits never accumulate subscriptions.
class RuntimeState {
 public:
  bool bind(const char *entity,const char *attribute,
            std::function<void(esphome::StringRef)> callback){
    const bool active=entity && *entity;
    const char *next=active?entity:"sensor.pi_panel_unassigned";
    const char *attr=attribute?attribute:"";
    if(registered_ && active==active_ && !strcmp(entity_,next) && !strcmp(attribute_,attr))return false;
    active_=active;
    snprintf(entity_,sizeof(entity_),"%s",next);
    snprintf(attribute_,sizeof(attribute_),"%s",attr);
    callback_=std::move(callback);
    if(!registered_){
      esphome::api::global_api_server->subscribe_home_assistant_state(entity_,attribute_,
        [this](esphome::StringRef value){if(active_)callback_(value);});
      registered_=true;
    }
    return true;
  }
 private:
  char entity_[97]{},attribute_[40]{};
  bool registered_=false,active_=false;
  std::function<void(esphome::StringRef)> callback_;
};
inline void refresh_runtime_subscriptions(){
  // A single reconnect asks HA to replace its complete subscription list.
  // Timers/brightness edits don't need this; only entity changes do.
  for(auto &client:esphome::api::global_api_server->active_clients()){
    if(!client->is_authenticated())continue;
    esphome::api::DisconnectRequest request;
    if(!client->send_message(request))client->on_disconnect_response();
  }
}
}
