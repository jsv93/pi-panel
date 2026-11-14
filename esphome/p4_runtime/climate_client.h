#pragma once
#include "esphome/components/api/api_server.h"
#include "esphome/core/helpers.h"
#include <algorithm>
#include <cmath>

namespace p4_runtime {
class ClimateClient {
 public:
  float temperature=NAN, humidity=NAN, target=NAN, minimum=7, maximum=35, step=.5f;
  bool available=false, running=false, dirty=true;
  void start(const char *temp,const char *hum,const char *thermostat){
    entity_=thermostat;
#ifdef STUDY_BENCH_TEST
    temperature=22.7f;humidity=56.7f;
    return;
#endif
    number(temp,nullptr,temperature);
    number(hum,nullptr,humidity);
    if(!*thermostat)return;
    if(!*temp)number(thermostat,"current_temperature",temperature);
    number(thermostat,"temperature",target);
    number(thermostat,"min_temp",minimum,7);
    number(thermostat,"max_temp",maximum,35);
    number(thermostat,"target_temp_step",step,.5f);
    esphome::api::global_api_server->subscribe_home_assistant_state(thermostat,nullptr,[this](esphome::StringRef s){
      const auto value=s.str();
      available=!value.empty() && value!="unavailable" && value!="unknown";
      running=available && value!="off";dirty=true;
    });
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
  const char *entity_="";
  void number(const char *entity,const char *attribute,float &dest,float missing=NAN){
    if(!*entity)return;
    esphome::api::global_api_server->subscribe_home_assistant_state(entity,attribute,[this,&dest,missing](esphome::StringRef s){
      auto value=esphome::parse_number<float>(s.str());
      dest=value && std::isfinite(*value)?*value:missing;dirty=true;
    });
  }
};
}
