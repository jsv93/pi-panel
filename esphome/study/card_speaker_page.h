#pragma once
#include "card_art.h"
#include "card_speakers.h"
#include <array>

namespace study {
class CardSpeakerPage {
  CardArt *art_=nullptr;
  uint8_t *packed_=nullptr;
  size_t capacity_=0;
  int selected_=-1;
  std::array<int,card_speaker_count> drawn_{};
  bool patch(const CardSpeakerPatch &p,uint8_t *frame,uint8_t *work,size_t bytes){
    const size_t size=2u*p.w*p.h;
    if(!art_ || size>bytes)return false;
    if(p.size>capacity_){
      auto *next=static_cast<uint8_t*>(heap_caps_realloc(packed_,p.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!next)return false;
      packed_=next;capacity_=p.size;
    }
    if(!art_->read(p.offset,packed_,p.size) || tinfl_decompress_mem_to_mem(work,size,packed_,p.size,1)!=size)return false;
    for(int y=0;y<p.h;++y)memcpy(frame+2*(720*(p.y+y)+p.x),work+2*y*p.w,2*p.w);
    return true;
  }
 public:
  bool attach(CardArt &art){
    if(!art.open(card_speakers_path,card_speakers_size,card_speakers_sha))return false;
    art_=&art;return true;
  }
  template<class Variant>
  bool paint(int theme,int mode,int selected,Variant variant,uint8_t *frame,uint8_t *work,size_t bytes,bool force){
    if(selected<0 || unsigned(selected)>=card_speaker_count)return false;
    bool changed=false;
    const unsigned base=theme*6+mode;
    if(force || selected!=selected_){
      if(!patch(card_speaker_heads[base*card_speaker_count+selected],frame,work,bytes))return false;
      selected_=selected;changed=true;
    }
    for(unsigned i=0;i<card_speaker_count;++i){
      int v=variant(i);
      if(!force && v==drawn_[i])continue;
      if(!patch(card_speaker_rows[(base*5+v)*card_speaker_count+i],frame,work,bytes))return false;
      drawn_[i]=v;changed=true;
    }
    return changed;
  }
};
}
