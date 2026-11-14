#pragma once
#include "card_art.h"
#include "card_assets.h"
#include "esp_heap_caps.h"

extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);

namespace study {
class CardScreen {
  CardArt *art_=nullptr;
  uint8_t *compressed_=nullptr;
  size_t capacity_=0;
 public:
  bool attach(CardArt &art){
    if(!art.open(card_pack_path,card_pack_size,card_pack_sha))return false;
    art_=&art;return true;
  }
  bool read(int theme,int palette,CardPage page,uint8_t *pixels,size_t bytes){
    const auto index=static_cast<size_t>(page);
    constexpr size_t pages=sizeof(card_frames[0][0])/sizeof(CardFrame);
    if(!art_ || !pixels || bytes!=2*720*1280 || theme<0 || theme>=2 || palette<0 || palette>=6 || index>=pages)return false;
    const auto &frame=card_frames[theme][palette][index];
    if(frame.size>capacity_){
      auto *larger=static_cast<uint8_t*>(heap_caps_realloc(compressed_,frame.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!larger)return false;
      compressed_=larger;capacity_=frame.size;
    }
    return art_->read(frame.offset,compressed_,frame.size) &&
      tinfl_decompress_mem_to_mem(pixels,bytes,compressed_,frame.size,1)==bytes;
  }
};
}
