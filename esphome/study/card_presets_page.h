#pragma once
#include "card_art.h"
#include "card_presets.h"

namespace study {
class CardPresetsPage {
  CardArt *art_=nullptr;
  uint8_t *encoded_=nullptr;
  size_t capacity_=0;
 public:
  bool attach(CardArt &art){
    if(!art.open(card_presets_path,card_presets_size,card_presets_sha))return false;
    art_=&art;return true;
  }
  bool paint(int theme,int palette,bool scene_page,int matches,uint8_t *pixels,uint8_t *work,size_t work_bytes){
    if(!art_ || !work || !pixels)return false;
    for(const auto &p:card_preset_patches){
      if(p.theme!=theme || p.palette!=palette || p.page!=int(scene_page) || p.active!=bool(p.mask&matches))continue;
      size_t size=size_t(p.w)*p.h*2;
      if(size>work_bytes)return false;
      if(p.size>capacity_){
        auto *more=static_cast<uint8_t*>(heap_caps_realloc(encoded_,p.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
        if(!more)return false;
        encoded_=more;capacity_=p.size;
      }
      if(!art_->read(p.offset,encoded_,p.size) || tinfl_decompress_mem_to_mem(work,size,encoded_,p.size,1)!=size)return false;
      for(int y=0;y<p.h;++y)memcpy(pixels+2*((p.y+y)*720+p.x),work+2*y*p.w,2*p.w);
    }
    return true;
  }
};
}
