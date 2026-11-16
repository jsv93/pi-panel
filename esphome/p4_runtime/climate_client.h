#pragma once
#include "esphome/components/api/api_server.h"
#include "esphome/core/helpers.h"
#include "runtime_state.h"
#include <algorithm>
#include <cmath>

namespace p4_runtime {
class ClimateClient {
 public:
  float temperature=NAN, humidity=NAN, target=NAN, minimum=7, maximum=35, step=.5f;
  bool available=false, running=false, dirty=true;
  bool start(const char *temp,const char *hum,const char *thermostat){
    if(started_ && !strcmp(temp,temp_) && !strcmp(hum,hum_) && !strcmp(thermostat,entity_))return false;
    started_=true;
    snprintf(entity_,sizeof(entity_),"%s",thermostat);
    snprintf(temp_,sizeof(temp_),"%s",temp);snprintf(hum_,sizeof(hum_),"%s",hum);
    temperature=humidity=target=NAN;minimum=7;maximum=35;step=.5f;available=running=false;dirty=true;
#ifdef STUDY_BENCH_TEST
    temperature=22.7f;humidity=56.7f;
    return false;
#endif
    number(0,*temp?temp:thermostat,*temp?nullptr:"current_temperature",temperature);
    number(1,hum,nullptr,humidity);
    number(2,thermostat,"temperature",target);
    number(3,thermostat,"min_temp",minimum,7);
    number(4,thermostat,"max_temp",maximum,35);
    number(5,thermostat,"target_temp_step",step,.5f);
    states_[6].bind(thermostat,nullptr,[this](esphome::StringRef s){
      const auto value=s.str();
      available=!value.empty() && value!="unavailable" && value!="unknown";
      running=available && value!="off";dirty=true;
    });
    return true;
  }
  bool can_adjust() const {
    return available && std::isfinite(target) && std::isfinite(minimum) && std::isfinite(maximum)
           && maximum>minimum && std::isfinite(step) && step>0;
  }
  bool set(float next){
    if(!can_adjust() || !std::isfinite(next))return false;
    next=std::clamp(next,minimum,maximum);
#ifdef STUDY_BENCH_TEST
    target=next;dirty=true;return true;
#else
    auto *api=esphome::api::global_api_server;
    if(!api->is_connected_with_state_subscription())return false;
    const auto value=std::to_string(next);
    esphome::api::HomeassistantActionRequest call;
    call.service=esphome::StringRef("climate.set_temperature");
    call.data.init(2);
    auto &entity=call.data.emplace_back();entity.key=esphome::StringRef("entity_id");entity.value=esphome::StringRef(entity_);
    auto &number=call.data.emplace_back();number.key=esphome::StringRef("temperature");number.value=esphome::StringRef(value);
    api->send_homeassistant_action(call);
    return true;
#endif
  }
  void tick(){
#ifndef STUDY_BENCH_TEST
    if(esphome::api::global_api_server->is_connected_with_state_subscription())return;
    if(available || std::isfinite(target) || std::isfinite(temperature) || std::isfinite(humidity)){
      available=running=false;temperature=humidity=target=NAN;dirty=true;
    }
#endif
  }
 private:
  char entity_[97]{},temp_[97]{},hum_[97]{};
  bool started_=false;
  RuntimeState states_[7];
  void number(int slot,const char *entity,const char *attribute,float &dest,float missing=NAN){
    states_[slot].bind(entity,attribute,[this,&dest,missing](esphome::StringRef s){
      auto value=esphome::parse_number<float>(s.str());
      dest=value && std::isfinite(*value)?*value:missing;dirty=true;
    });
  }
};
}
