#pragma once
#include "esphome/components/api/homeassistant_service.h"
#include <esp_timer.h>
#include <string>
#include <vector>
#include <algorithm>

namespace p4_runtime {
class LibraryClient {
 public:
  struct Item {std::string id,type,title,category,thumbnail; bool expand,play;};
  std::vector<Item> items,folders;
  bool dirty=false,waiting=false;
  const char *message="";
  size_t first=0,total=0;
  // Keep several screens on either side of the viewport. A response replaces
  // the window only after it arrives; pagination must not blank a moving list.
  static constexpr size_t batch=40,lookahead=40;
  void open(const char *entity){
    entity_=entity;folders.clear();get(0,true);
  }
  void close(){++serial_;waiting=false;items.clear();folders.clear();}
  void up(){if(!folders.empty())folders.pop_back();get(0,true);}
  void choose(size_t index){
    if(index>=items.size())return;
    if(items[index].expand){folders.push_back(items[index]);get(0,true);}
    else if(items[index].play)play(items[index]);
  }
  void ensure(size_t visible,size_t count){
    visible_=visible;visible_count_=count;
    if(waiting || esp_timer_get_time()<retry_at_)return;
    if(visible<first || visible+count+12>first+items.size()){
      if(visible>=first && first+items.size()>=total)return;
      const size_t offset=visible>20?(visible-20)/batch*batch:0;
      get(offset);
    }
  }
  void get(size_t offset,bool reset=false){
    auto *api=esphome::api::global_api_server;
    const auto generation=++serial_;
    if(reset){first=offset;dirty=true;items.clear();total=0;visible_=visible_count_=0;}
    waiting=false;
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
    waiting=true;deadline_=esp_timer_get_time()+15000000;
    message=items.empty()?"Loading…":"";
    api->register_action_response_callback(r.call_id,[this,generation,offset](const esphome::api::ActionResponse &result){
      if(serial_!=generation)return;
      waiting=false;retry_at_=esp_timer_get_time()+3000000;
      if(items.empty()){dirty=true;message="This player can’t browse";total=0;}
      if(!result.is_success())return;
      auto data=result.get_json()["response"];
      if(!data["rows"].is<JsonArrayConst>())return;
      std::vector<Item> incoming;
      for(auto row:data["rows"].as<JsonArrayConst>()){
        if(incoming.size()==batch+lookahead || row.size()!=7)break;
        incoming.push_back({row[0]|"",row[1]|"",row[2]|"",row[3]|"",row[4]|"",row[5]|false,row[6]|false});
      }
      const size_t available=data["total"].as<size_t>();
      // A fling can reverse before prefetch completes. Do not replace the
      // visible window with a response for a location the finger has left.
      if(!items.empty() && (offset>visible_ || offset+incoming.size()<std::min(available,visible_+visible_count_))){retry_at_=0;return;}
      items=std::move(incoming);first=offset;total=available;
      dirty=true;retry_at_=0;
      message=items.empty()?"Nothing here":"";
      ESP_LOGI("study","Music library received %u of %u items",unsigned(items.size()),unsigned(total));
    });
    api->send_homeassistant_action(r);
  }
  void tick(){
    if(waiting && esp_timer_get_time()>deadline_){
      ++serial_;waiting=false;retry_at_=esp_timer_get_time()+3000000;
      if(items.empty()){dirty=true;message="This player can’t browse";}
    }
  }
 private:
  const char *entity_="";
  uint32_t serial_=0;
  int64_t deadline_=0,retry_at_=0;
  size_t visible_=0,visible_count_=0;
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
