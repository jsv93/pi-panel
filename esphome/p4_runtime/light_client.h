#pragma once

#include "esphome/components/api/api_server.h"
#include "esphome/core/helpers.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <cstdlib>

namespace p4_runtime {
// A confirmed level comes from HA. Slider previews are local and are never
// queued for later delivery: reconnecting must not replay an old room command.
template<size_t N> class LightClient {
 public:
  using Handler = std::function<void(size_t, int)>;
  struct Detail {
    bool dimmable=false;
    int kelvin=-1,minimum=2000,maximum=6500,hue=-1;
    std::string effect;
    bool dirty=true;
  };
  const Detail &detail(size_t i)const{return detail_[i];}
  bool take_detail(size_t i){bool d=detail_[i].dirty;detail_[i].dirty=false;return d;}
  void start(const char *const (&entities)[N], Handler changed) {
    entities_=entities;
    changed_=std::move(changed);
#ifdef STUDY_BENCH_TEST
    for(size_t i=0;i<N;i++){
      lights_[i].power=1;lights_[i].brightness=17+int(i)*11;notify(i);
    }
    return;
#endif
    for(size_t i=0;i<N;i++){
      auto *api=esphome::api::global_api_server;
      auto attr=[this,i,api](const char *name,auto update){
        api->subscribe_home_assistant_state(entities_[i],name,[this,i,update](esphome::StringRef s){
          update(detail_[i],s.str());detail_[i].dirty=true;
        });
      };
      attr("effect",[](Detail &d,const std::string &s){d.effect=s;});
      attr("supported_color_modes",[](Detail &d,const std::string &s){
        d.dimmable=false;
        for(const char *name:{"brightness","color_temp","hs","xy","rgb","white"})
          if(s.find(name)!=std::string::npos){d.dimmable=true;break;}
      });
      attr("color_temp_kelvin",[](Detail &d,const std::string &s){d.kelvin=esphome::parse_number<int>(s).value_or(-1);});
      attr("min_color_temp_kelvin",[](Detail &d,const std::string &s){d.minimum=esphome::parse_number<int>(s).value_or(2000);});
      attr("max_color_temp_kelvin",[](Detail &d,const std::string &s){d.maximum=esphome::parse_number<int>(s).value_or(6500);});
      attr("hs_color",[](Detail &d,const std::string &s){
        char *end=nullptr;
        auto start=s.find_first_not_of(" [(\t");
        const char *p=start==std::string::npos?"":s.c_str()+start;
        double hue=strtod(p,&end);
        d.hue=end!=p && *end==',' && hue>=0 && hue<=360?int(std::lround(hue)):-1;
      });
      api->subscribe_home_assistant_state(entities_[i],nullptr,[this,i](esphome::StringRef value){
        received_=true;
        auto state=value.str();
        lights_[i].power=state=="on"?1:state=="off"?0:-1;
        notify(i);
      });
      api->subscribe_home_assistant_state(entities_[i],"brightness",[this,i](esphome::StringRef value){
        auto brightness=esphome::parse_number<int>(value.str());
        lights_[i].brightness=brightness && *brightness>=0 && *brightness<=255
                                  ?std::lround(*brightness*100.0/255):-1;
        notify(i);
      });
    }
  }
  void tick() {
#ifdef STUDY_BENCH_TEST
    return;
#endif
    auto *api=esphome::api::global_api_server;
    if(api->is_connected_with_state_subscription())return;
    received_=false;
    for(size_t i=0;i<N;i++){
      if(lights_[i].power<0 && lights_[i].brightness<0)continue;
      lights_[i]=State{};
      detail_[i]=Detail{};
      notify(i);
    }
  }
  bool receiving() const {return received_;}
  bool request(size_t i,int percent) {
#ifdef STUDY_BENCH_TEST
    if(i>=N || percent<0 || percent>100 || lights_[i].power<0)return false;
    lights_[i].power=percent?1:0;lights_[i].brightness=percent;notify(i);return true;
#endif
    if(i>=N || percent<0 || percent>100 || lights_[i].power<0 ||
       !esphome::api::global_api_server->is_connected_with_state_subscription())return false;
    using esphome::StringRef;
    esphome::api::HomeassistantActionRequest call;
    call.service=StringRef(percent?"light.turn_on":"light.turn_off");
    call.data.init(percent?2:1);
    auto &target=call.data.emplace_back();
    target.key=StringRef("entity_id");
    target.value=StringRef(entities_[i]);
    const auto level=std::to_string(percent);
    if(percent){
      auto &v=call.data.emplace_back();
      v.key=StringRef("brightness_pct");
      v.value=StringRef(level);
    }
    esphome::api::global_api_server->send_homeassistant_action(call);
    return true;
  }
  int confirmed(size_t i) const {
    return lights_[i].power==1 ? std::max(1,lights_[i].brightness<0?100:lights_[i].brightness) : lights_[i].power;
  }
  enum class Property { warmth,colour,effect };
  bool adjust(size_t i,Property property,int value,const char *effect=nullptr){
    if(i>=N || confirmed(i)<0)return false;
    auto &d=detail_[i];
    if(property==Property::warmth && (value<d.minimum || value>d.maximum))return false;
    if(property==Property::colour && (value<0 || value>360))return false;
    if(property==Property::effect && (!effect || !*effect))return false;
#ifdef STUDY_BENCH_TEST
    if(property==Property::warmth)d.kelvin=value;
    if(property==Property::colour)d.hue=value;
    if(property==Property::effect)d.effect=effect;
    d.dirty=true;
#else
    if(!esphome::api::global_api_server->is_connected_with_state_subscription())return false;
    using esphome::StringRef;
    esphome::api::HomeassistantActionRequest call;
    call.service=StringRef("light.turn_on");
    const bool colour=property==Property::colour;
    call.data.init(colour?1:2);
    auto &target=call.data.emplace_back();
    target.key=StringRef("entity_id");target.value=StringRef(entities_[i]);
    if(colour)call.data_template.init(1);
    auto &arg=colour?call.data_template.emplace_back():call.data.emplace_back();
    const auto text=colour?"{{ ["+std::to_string(value)+", 85] }}":
        property==Property::warmth?std::to_string(value):std::string(effect);
    arg.key=StringRef(colour?"hs_color":property==Property::warmth?"color_temp_kelvin":"effect");
    arg.value=StringRef(text);
    esphome::api::global_api_server->send_homeassistant_action(call);
#endif
    return true;
  }
 private:
  struct State { int power=-1,brightness=-1; };
  std::array<State,N> lights_{};
  std::array<int,N> notified_{};
  std::array<bool,N> has_notified_{};
  std::array<Detail,N> detail_{};
  const char *const *entities_{};
  Handler changed_;
  bool received_=false;
  void notify(size_t i) {
    const int value=confirmed(i);
    // HA sends power and brightness separately and may repeat unchanged
    // state. An identical echo must not replace an in-progress local preview.
    if(has_notified_[i] && notified_[i]==value)return;
    has_notified_[i]=true;notified_[i]=value;changed_(i,value);
  }
};
}
