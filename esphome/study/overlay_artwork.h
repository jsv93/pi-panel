#pragma once
#include "overlay_assets.h"
#include "card_art.h"
#include <iterator>
#include <utility>
#include <atomic>
#include "esp_timer.h"
extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);

namespace study {
class OverlayArtwork {
  CardArt file_;
  uint8_t *packed_=nullptr;
  size_t capacity_=0;
  std::atomic<int> state_{0};
  std::atomic<uint32_t> retry_at_{0};
  struct CachedPacket {unsigned offset=0,size=0;uint8_t *data=nullptr;};
  CachedPacket packets_[8];
  unsigned next_packet_=0;
  bool inflate(const unsigned *section,uint8_t *out,size_t count){
    if(section[0]>overlay_size || section[1]>overlay_size-section[0])return false;
    for(const auto &packet:packets_)
      if(packet.data && packet.offset==section[0] && packet.size==section[1])
        return tinfl_decompress_mem_to_mem(out,count,packet.data,packet.size,1)==count;
    if(section[1]>capacity_){
      auto *buffer=static_cast<uint8_t*>(heap_caps_realloc(packed_,section[1],MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!buffer)return false;
      packed_=buffer;capacity_=section[1];
    }
    if(!file_.read(section[0],packed_,section[1]))return false;
    // Repeated timeline and text patches stay in a bounded 32 KiB cache.
    if(section[1]<=4096){
      auto &packet=packets_[next_packet_++%std::size(packets_)];
      auto *data=static_cast<uint8_t*>(heap_caps_realloc(packet.data,section[1],MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(data){
        memcpy(data,packed_,section[1]);
        packet={section[0],section[1],data};
      }
    }
    return tinfl_decompress_mem_to_mem(out,count,packed_,section[1],1)==count;
  }
  bool image(const OverlayImage *first,const OverlayImage *end,unsigned source,unsigned source_size,
             int palette,uint8_t *out,size_t count){
    if(!ready() || palette<0 || palette>=6)return false;
    const auto *entry=std::lower_bound(first,end,std::pair{source,source_size},
      [](const OverlayImage &image,const auto &key){return std::pair{image.source,image.size}<key;});
    if(entry==end || entry->source!=source || entry->size!=source_size || entry->raw!=count)return false;
    return inflate(entry->variants[palette],out,count);
  }
 public:
  bool begin(bool force=false){
    int state=state_.load();
    if(state==2)return true;
    const uint32_t now=esp_timer_get_time()/1000,retry=retry_at_.load();
    if(state==1 || (!force && retry && int32_t(now-retry)<0) ||
       !state_.compare_exchange_strong(state,1))return false;
    const bool loaded=file_.mount() && file_.open(overlay_path,overlay_size,overlay_sha);
    if(!loaded)retry_at_.store(uint32_t(esp_timer_get_time()/1000)+30000);
    state_.store(loaded?2:0);
    return loaded;
  }
  void warm(){
    if(ready())return;
    if(xTaskCreate([](void *context){
        auto *art=static_cast<OverlayArtwork*>(context);
        ESP_LOGI("study","Overlay palettes %s",art->begin()?"ready":"unavailable");
        vTaskDelete(nullptr);
      },"study_palette",8192,this,1,nullptr)!=pdPASS)
      ESP_LOGW("study","Overlay palette preload unavailable");
  }
  bool ready()const{return state_.load()==2;}
#ifdef STUDY_OVERLAY_WIFI
  const OverlayWifiRow *wifi(int palette,bool selected,bool secure,int signal,uint8_t *out,size_t count){
    if(!ready() || palette<0 || palette>=6)return nullptr;
    const int band=signal>=100?5:signal>=75?4:signal>=50?3:signal>=25?2:signal>=10?1:0;
    const auto &row=overlay_wifi_rows[palette][12*int(selected)+6*int(secure)+band];
    const unsigned section[]={row.offset,row.size};
    return inflate(section,out,count)?&row:nullptr;
  }
#endif
  bool expand(unsigned source,unsigned source_size,int palette,uint8_t *out,size_t count){
    return image(std::begin(overlay_images),std::end(overlay_images),source,source_size,palette,out,count);
  }
#ifdef STUDY_OVERLAY_CONTROLS
  bool control(unsigned source,unsigned source_size,int palette,uint8_t *out,size_t count){
    return image(std::begin(overlay_controls),std::end(overlay_controls),source,source_size,palette,out,count);
  }
  bool volume(int palette,int kind,int level,uint8_t *out,size_t count,size_t capacity){
    if(!ready() || palette<0 || palette>=6 || kind<0 || kind>1 || level<0 || level>100 ||
       count>capacity/2 || count%2)return false;
    if(!inflate(overlay_volume_bases[palette][kind],out,count) ||
       !inflate(overlay_volume_levels[palette][kind][level],out+count,count))return false;
    auto *pixels=reinterpret_cast<uint16_t*>(out);
    const auto *delta=reinterpret_cast<const uint16_t*>(out+count);
    for(size_t i=0;i<count/2;++i)pixels[i]^=delta[i];
    return true;
  }
#endif
  uint16_t colour(unsigned source,unsigned size,unsigned original,unsigned font,int palette)const{
    if(palette<0 || palette>=6)return original;
    for(const auto &field:overlay_colours)
      if(field.source==source && field.size==size && field.colour==original && field.font==font)
        return field.variants[palette];
    return original;
  }
};
static OverlayArtwork overlay_artwork;
static int text_palette=-1;
static bool overlay_frame=false;
class TextPaletteScope {
  int previous_;
 public:
  explicit TextPaletteScope(int selected,bool complete_frame=true):previous_(text_palette){
    text_palette=selected>=0 && overlay_artwork.begin()?selected:-1;
    if(complete_frame)overlay_frame=text_palette>=0;
  }
  ~TextPaletteScope(){text_palette=previous_;}
};
}
