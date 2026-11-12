#pragma once

#include "esphome/components/api/api_server.h"
#include "esphome/core/helpers.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <functional>

namespace p4_runtime {
// A confirmed level comes from HA. Slider previews are local and are never
// queued for later delivery: reconnecting must not replay an old room command.
template<size_t N> class LightClient {
 public:
  using Handler = std::function<void(size_t, int)>;
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
 private:
  struct State { int power=-1,brightness=-1; };
  std::array<State,N> lights_{};
  const char *const *entities_{};
  Handler changed_;
  bool received_=false;
  void notify(size_t i) {changed_(i,confirmed(i));}
};
}
