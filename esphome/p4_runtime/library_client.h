#pragma once
#include "esphome/components/api/homeassistant_service.h"
#include <esp_timer.h>
#include <string>
#include <vector>

namespace p4_runtime {
class LibraryClient {
 public:
  struct Item {std::string id,type,title,category,thumbnail; bool expand,play;};
  std::vector<Item> items,folders;
  bool dirty=false,waiting=false;
  const char *message="";
  size_t first=0,total=0;
  static constexpr size_t batch=20,lookahead=10;
  void open(const char *entity){
    entity_=entity;folders.clear();get(0);
  }
  void close(){++serial_;waiting=false;items.clear();folders.clear();}
  void up(){folders.pop_back();get(0);}
  void choose(size_t index){
    if(waiting || index>=items.size())return;
    if(items[index].expand){folders.push_back(items[index]);get(0);}
    else if(items[index].play)play(items[index]);
  }
  void get(size_t offset){
    auto *api=esphome::api::global_api_server;
    const auto generation=++serial_;
    first=offset;dirty=true;items.clear();waiting=false;
    if(!*entity_ || !api->is_connected_with_state_subscription()){message="This player can’t browse";total=0;return;}
    esphome::api::HomeassistantActionRequest r;
    r.service=esphome::StringRef("media_player.browse_media");
    r.data.init(folders.empty()?1:3);
    add(r,"entity_id",entity_);
    if(!folders.empty()){add(r,"media_content_id",folders.back().id.c_str());add(r,"media_content_type",folders.back().type.c_str());}
    std::string format="{% set kids=response['"+std::string(entity_)+"']['children'] %}"
      "{% set ns=namespace(rows=[]) %}{% for c in kids["+std::to_string(offset)+":"+std::to_string(offset+batch+lookahead)+"] %}"
      "{% set ns.rows=ns.rows+[[c.media_content_id,c.media_content_type,c.title,c.media_class,c.thumbnail|default('',true),c.can_expand,c.can_play]] %}"
      "{% endfor %}{{ {'total': kids|length,'rows':ns.rows} }}";
    r.response_template=esphome::StringRef(format);r.wants_response=true;r.call_id=0x40000000u|generation;
    waiting=true;deadline_=esp_timer_get_time()+15000000;message="Loading…";
    api->register_action_response_callback(r.call_id,[this,generation](const esphome::api::ActionResponse &result){
      if(serial_!=generation)return;
      dirty=true;waiting=false;message="This player can’t browse";total=0;
      if(!result.is_success())return;
      auto data=result.get_json()["response"];
      if(!data["rows"].is<JsonArrayConst>())return;
      total=data["total"].as<size_t>();
      for(auto row:data["rows"].as<JsonArrayConst>()){
        if(items.size()==batch+lookahead || row.size()!=7)break;
        items.push_back({row[0]|"",row[1]|"",row[2]|"",row[3]|"",row[4]|"",row[5]|false,row[6]|false});
      }
      message=items.empty()?"Nothing here":"";
      ESP_LOGI("study","Music library received %u of %u items",unsigned(items.size()),unsigned(total));
    });
    api->send_homeassistant_action(r);
  }
  void tick(){
    if(waiting && esp_timer_get_time()>deadline_){
      ++serial_;waiting=false;dirty=true;message="This player can’t browse";
    }
  }
 private:
  const char *entity_="";
  uint32_t serial_=0;
  int64_t deadline_=0;
  using Request=esphome::api::HomeassistantActionRequest;
  static void add(Request &r,const char *k,const char *v){
    auto &kv=r.data.emplace_back();kv.key=esphome::StringRef(k);kv.value=esphome::StringRef(v);
  }
  void play(const Item &item){
    auto *api=esphome::api::global_api_server;
    if(!api->is_connected_with_state_subscription())return;
    Request r;r.service=esphome::StringRef("media_player.play_media");r.data.init(3);
    add(r,"entity_id",entity_);add(r,"media_content_type",item.type.c_str());add(r,"media_content_id",item.id.c_str());
    api->send_homeassistant_action(r);
  }
};
}
