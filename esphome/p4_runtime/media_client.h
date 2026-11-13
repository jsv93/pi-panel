#pragma once
#include "esphome/components/api/api_server.h"
#include <string>
#include <cmath>
#include "esphome/core/time.h"
#include <esp_timer.h>

namespace p4_runtime {
// Transport goes directly through the encrypted HA connection. Never replay
// a press after a disconnect or choose another speaker when one is offline.
class MediaClient {
 public:
  enum Control { shuffle, previous, play_pause, next, repeat };
  bool available=false, playing=false, shuffled=false, dirty=true;
  int repeat_mode=0,volume=-1;
  std::string title,artist,playlist,album,picture,queue,player_type;
  bool paused=false;
  int duration=0;
  bool can_seek=false;
  double position()const{
    double age=playing?(esp_timer_get_time()-position_at_)/1e6:0;
    if(playing && updated_at_>0){
      const double reported=difftime(::time(nullptr),updated_at_);
      if(reported>=0 && reported<86400)age=reported;
    }
    return std::clamp(reported_position_+age,0.,double(duration));
  }
  void start(const char *speaker){
    speaker_=speaker;
    if(!*speaker_)return;
#ifdef STUDY_BENCH_TEST
    available=true;volume=45;can_seek=true;
#else
    auto *api=esphome::api::global_api_server;
    auto text=[this,api](const char *attribute,std::string *field){
      api->subscribe_home_assistant_state(speaker_,attribute,[this,field](esphome::StringRef s){
        auto value=s.str();if(value=="None" || value=="unknown" || value=="unavailable")value.clear();
        if(value.size()>512)value.resize(512);
        if(*field!=value){*field=std::move(value);dirty=true;}
      });
    };
    text("media_title",&title);text("media_artist",&artist);
    text("media_playlist",&playlist);text("media_album_name",&album);
    text("active_queue",&queue);text("mass_player_type",&player_type);
    api->subscribe_home_assistant_state(speaker_,"entity_picture",[this](esphome::StringRef s){
      auto v=s.str();if(v=="None" || v.size()>=1536)v.clear();
      if(picture!=v){picture=std::move(v);dirty=true;}
    });
    api->subscribe_home_assistant_state(speaker_,"media_duration",[this](esphome::StringRef s){
      auto n=esphome::parse_number<float>(s.str());duration=n && std::isfinite(*n) && *n>0 && *n<864000?std::lround(*n):0;dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"media_position",[this](esphome::StringRef s){
      auto n=esphome::parse_number<float>(s.str());
      if(n && std::isfinite(*n)){reported_position_=std::max(0.f,*n);position_at_=esp_timer_get_time();}
      dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"media_position_updated_at",[this](esphome::StringRef s){
      updated_at_=0;auto timestamp=s.str();
      if(timestamp.size()<19 || timestamp[10]!='T')return;
      auto local=timestamp.substr(0,19);local[10]=' ';esphome::ESPTime parsed{};
      if(!esphome::ESPTime::strptime(local,parsed))return;
      parsed.recalc_timestamp_utc(false);
      auto zone=timestamp.find_first_of("+-",19);int hours=0,minutes=0;
      if(zone!=std::string::npos && sscanf(timestamp.c_str()+zone+1,"%2d:%2d",&hours,&minutes)==2)
        parsed.timestamp+=(timestamp[zone]=='+'?-1:1)*(hours*3600+minutes*60);
      updated_at_=parsed.timestamp;dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"supported_features",[this](esphome::StringRef s){
      can_seek=(esphome::parse_number<unsigned>(s.str()).value_or(0)&16)!=0;dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,nullptr,[this](esphome::StringRef s){
      const auto state=s.str();
      available=!state.empty() && state!="unknown" && state!="unavailable";
      playing=state=="playing";paused=state=="paused";dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"shuffle",[this](esphome::StringRef s){
      shuffled=s.str()=="True" || s.str()=="true" || s.str()=="on";dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"repeat",[this](esphome::StringRef s){
      repeat_mode=s.str()=="one"?2:s.str()=="all"?1:0;dirty=true;
    });
    api->subscribe_home_assistant_state(speaker_,"volume_level",[this](esphome::StringRef s){
      const auto value=esphome::parse_number<float>(s.str());
      volume=value && std::isfinite(*value) && *value>=0 && *value<=1?std::lround(*value*100):-1;
      dirty=true;
    });
#endif
  }
  void tick(){
#ifndef STUDY_BENCH_TEST
    if(available && !esphome::api::global_api_server->is_connected_with_state_subscription()){
      available=playing=shuffled=false;repeat_mode=0;volume=-1;dirty=true;
      title.clear();artist.clear();playlist.clear();album.clear();picture.clear();player_type.clear();queue.clear();
      paused=false;duration=0;can_seek=false;updated_at_=0;
    }
#endif
  }
  bool set_volume(int pct){
    if(!available || pct<0 || pct>100)return false;
#ifdef STUDY_BENCH_TEST
    volume=pct;dirty=true;
#else
    return send_value("media_player.volume_set","volume_level",std::to_string(pct/100.));
#endif
    return true;
  }
  bool seek(int seconds){
    if(!available || !can_seek || !duration || seconds<0 || seconds>duration)return false;
#ifndef STUDY_BENCH_TEST
    if(!send_value("media_player.media_seek","seek_position",std::to_string(seconds)))return false;
#endif
    reported_position_=seconds;position_at_=esp_timer_get_time();updated_at_=0;dirty=true;return true;
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
  double reported_position_=0;
  int64_t position_at_=0;
  time_t updated_at_=0;
  bool send_value(const char *service,const char *key,const std::string &value){
    auto *api=esphome::api::global_api_server;
    if(!api->is_connected_with_state_subscription())return false;
    using esphome::StringRef;
    esphome::api::HomeassistantActionRequest action;action.service=StringRef(service);action.data.init(2);
    auto &target=action.data.emplace_back();target.key=StringRef("entity_id");target.value=StringRef(speaker_);
    auto &arg=action.data.emplace_back();arg.key=StringRef(key);arg.value=StringRef(value);
    api->send_homeassistant_action(action);return true;
  }
  const char *speaker_="";
};
}
