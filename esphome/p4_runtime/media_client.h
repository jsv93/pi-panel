#pragma once
#include "esphome/components/api/api_server.h"
#include <string>

namespace p4_runtime {
// Transport goes directly through the encrypted HA connection. Never replay
// a press after a disconnect or choose another speaker when one is offline.
class MediaClient {
 public:
  enum Control { shuffle, previous, play_pause, next, repeat };
  bool available=false, playing=false, shuffled=false, dirty=true;
  int repeat_mode=0;
  void start(const char *speaker){
    speaker_=speaker;
    if(!*speaker_)return;
#ifdef STUDY_BENCH_TEST
    available=true;
#else
    auto *api=esphome::api::global_api_server;
    api->subscribe_home_assistant_state(speaker_,nullptr,[this](esphome::StringRef s){
      const auto state=s.str();
      available=!state.empty() && state!="unknown" && state!="unavailable";
      playing=state=="playing";dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"shuffle",[this](esphome::StringRef s){
      shuffled=s.str()=="True" || s.str()=="true" || s.str()=="on";dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"repeat",[this](esphome::StringRef s){
      repeat_mode=s.str()=="one"?2:s.str()=="all"?1:0;dirty=true;
    });
#endif
  }
  void tick(){
#ifndef STUDY_BENCH_TEST
    if(available && !esphome::api::global_api_server->is_connected_with_state_subscription()){
      available=playing=shuffled=false;repeat_mode=0;dirty=true;
    }
#endif
  }
  bool press(Control key){
    if(!available)return false;
    const char *service=nullptr,*attribute=nullptr,*value=nullptr;
    switch(key){
      case play_pause:service=playing?"media_player.media_pause":"media_player.media_play";break;
      case previous:service="media_player.media_previous_track";break;
      case next:service="media_player.media_next_track";break;
      case shuffle:service="media_player.shuffle_set";attribute="shuffle";value=shuffled?"false":"true";break;
      case repeat:service="media_player.repeat_set";attribute="repeat";value=repeat_mode==0?"all":repeat_mode==1?"one":"off";break;
      default:return false;
    }
#ifdef STUDY_BENCH_TEST
    last_service=service;
    if(key==play_pause)playing=!playing;
    if(key==shuffle)shuffled=!shuffled;
    if(key==repeat)repeat_mode=(repeat_mode+1)%3;
    dirty=true;
#else
    auto *api=esphome::api::global_api_server;
    if(!api->is_connected_with_state_subscription())return false;
    using esphome::StringRef;
    esphome::api::HomeassistantActionRequest action;
    action.service=StringRef(service);action.data.init(attribute?2:1);
    auto &target=action.data.emplace_back();target.key=StringRef("entity_id");target.value=StringRef(speaker_);
    if(attribute){
      auto &arg=action.data.emplace_back();arg.key=StringRef(attribute);arg.value=StringRef(value);
    }
    api->send_homeassistant_action(action);
#endif
    return true;
  }
#ifdef STUDY_BENCH_TEST
  std::string last_service;
#endif
 private:
  const char *speaker_="";
};
}
