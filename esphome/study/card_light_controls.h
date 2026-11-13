#pragma once
#include "card_art.h"
#include "card_lights.h"
#include "esp_heap_caps.h"
extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);

namespace study {
class CardLightControls {
  CardArt *art_=nullptr;
  uint8_t *encoded_=nullptr;
  size_t capacity_=0;
  struct Patch {uint32_t offset,bytes;};
 public:
  bool attach(CardArt &art){
    if(!art.open(card_lights_path,card_lights_size,card_lights_sha))return false;
    art_=&art;return true;
  }
  int hit(int theme,int x,int y)const{
    if(theme<0 || theme>=2)return -1;
    for(unsigned i=0;i<card_light_count;i++){
      const auto &r=card_light_rects[theme][i][0];
      if(x>=r.x && x<r.x+r.w && y>=r.y && y<r.y+r.h)return i;
    }
    return -1;
  }
  int level(int theme,int light,int x)const{
    if(theme<0 || theme>=2 || light<0 || unsigned(light)>=card_light_count)return -1;
    const auto &r=card_light_rects[theme][light][0];
    return std::clamp(((x-r.x)*100+r.w/2)/r.w,0,100);
  }
  bool paint(int theme,int palette,int light,int percent,uint8_t *frame,uint8_t *scratch,size_t available){
    if(!art_ || !frame || !scratch || theme<0 || theme>=2 || palette<0 || palette>=6 ||
       light<0 || unsigned(light)>=card_light_count || percent<0 || percent>100)return false;
    Patch pair[2];
    const size_t at=card_light_tables[theme][palette]+sizeof(pair)*(percent*card_light_count+light);
    if(!art_->read(at,pair,sizeof(pair)))return false;
    for(int index=0;index<2;index++){
      auto patch=pair[index];
      const auto &r=card_light_rects[theme][light][index+1];
      const size_t bytes=2*r.w*r.h;
      if(bytes>available)return false;
      if(patch.bytes>capacity_){
        auto *more=static_cast<uint8_t*>(heap_caps_realloc(encoded_,patch.bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
        if(!more)return false;
        encoded_=more;capacity_=patch.bytes;
      }
      if(!art_->read(patch.offset,encoded_,patch.bytes) ||
         tinfl_decompress_mem_to_mem(scratch,bytes,encoded_,patch.bytes,1)!=bytes)return false;
      for(int y=0;y<r.h;y++)memcpy(frame+2*((r.y+y)*720+r.x),scratch+2*y*r.w,2*r.w);
    }
    return true;
  }
};
}
