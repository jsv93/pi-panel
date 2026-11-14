#pragma once
#include "navigation_art_assets.h"
#include "card_art.h"
#include "esp_timer.h"
#include <atomic>

namespace study {
class NavigationArtwork {
  struct Frame {uint32_t offset,bytes;};
  static constexpr unsigned frames_per_route=10;
  static constexpr unsigned tiles_per_page=(720/16)*(1280/8);
  static constexpr size_t index_count=6*sd_navigation_routes*frames_per_route;
  CardArt file_;
  Frame *frames_=nullptr;
  std::atomic<int> state_{0};
  std::atomic<uint32_t> retry_at_{0};

  bool load(){
    if(!file_.mount() || !file_.open(sd_navigation_path,sd_navigation_size,sd_navigation_sha))return false;
    auto *frames=static_cast<Frame*>(heap_caps_malloc(index_count*sizeof(Frame),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    bool valid=frames && file_.read(sd_navigation_index,frames,index_count*sizeof(Frame));
    const size_t first_frame=sd_navigation_hashes+6*sd_navigation_pages*tiles_per_page*4;
    for(size_t i=0;valid && i<index_count;++i){
      const auto &frame=frames[i];
      valid=frame.offset>=first_frame && frame.offset<=sd_navigation_size && frame.bytes &&
            frame.bytes<=sd_navigation_max_frame && frame.bytes<=sd_navigation_size-frame.offset;
    }
    if(!valid){heap_caps_free(frames);file_.close();return false;}
    frames_=frames;
    return true;
  }

 public:
  bool ready()const{return state_.load()==2;}
  void warm(){
    if(ready())return;
    const uint32_t now=esp_timer_get_time()/1000,retry=retry_at_.load();
    if(retry && int32_t(now-retry)<0)return;
    int idle=0;
    if(!state_.compare_exchange_strong(idle,1))return;
    if(xTaskCreate([](void *context){
        auto &self=*static_cast<NavigationArtwork*>(context);
        const bool loaded=self.load();
        if(!loaded)self.retry_at_.store(uint32_t(esp_timer_get_time()/1000)+30000);
        self.state_.store(loaded?2:0);
        ESP_LOGI("study","SD navigation artwork %s",loaded?"ready":"unavailable");
        vTaskDelete(nullptr);
      },"study_nav_art",8192,this,1,nullptr)!=pdPASS){
      retry_at_.store(now+30000);
      state_.store(0);
    }
  }
  unsigned frame_size(unsigned palette,unsigned route,unsigned phase)const{
    if(!ready() || palette>=6 || route>=sd_navigation_routes || phase>=frames_per_route)return 0;
    return frames_[(palette*sd_navigation_routes+route)*frames_per_route+phase].bytes;
  }
  bool frame(unsigned palette,unsigned route,unsigned phase,uint8_t *destination,size_t capacity){
    const auto bytes=frame_size(palette,route,phase);
    if(!bytes || bytes>capacity)return false;
    const auto &frame=frames_[(palette*sd_navigation_routes+route)*frames_per_route+phase];
    return file_.read(frame.offset,destination,bytes);
  }
  bool hashes(unsigned palette,unsigned page,uint32_t *destination){
    if(!ready() || palette>=6 || page>=sd_navigation_pages)return false;
    const size_t offset=sd_navigation_hashes+(palette*sd_navigation_pages+page)*tiles_per_page*4;
    return file_.read(offset,destination,tiles_per_page*4);
  }
};
static NavigationArtwork navigation_artwork;
}
