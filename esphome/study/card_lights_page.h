#pragma once
#include "card_screen.h"
#include "card_light_controls.h"
#include <array>

namespace study {
// The preview follows the finger. After release the labels follow HA's
// confirmed values, including a rejected action or a remote change.
class CardLightsPage {
  CardScreen &screens_;
  CardLightControls &controls_;
  uint8_t *frame_=nullptr,*scratch_=nullptr;
  size_t scratch_bytes_=0;
  int theme_=0,palette_=0,drag_=-1,preview_=-1;
  std::array<int,card_light_count> displayed_{};

  bool row(int light,int value){
    const int level=std::max(0,value);
    if(displayed_[light]==level)return true;
    if(!controls_.paint(theme_,palette_,light,level,frame_,scratch_,scratch_bytes_))return false;
    displayed_[light]=level;
    return true;
  }
 public:
  CardLightsPage(CardScreen &screens,CardLightControls &controls):screens_(screens),controls_(controls){}
  bool slider_at(int x,int y)const{return controls_.hit(theme_,x,y)>=0;}
  template<class Lights>
  bool open(int theme,int palette,uint8_t *frame,uint8_t *scratch,size_t scratch_bytes,const Lights &lights){
    if(!scratch || !screens_.read(theme,palette,CardPage::lights,frame,720*1280*2))return false;
    theme_=theme;palette_=palette;frame_=frame;scratch_=scratch;scratch_bytes_=scratch_bytes;
    cancel();displayed_.fill(-1);
    for(unsigned i=0;i<card_light_count;++i)if(!row(i,lights.confirmed(i)))return false;
    return true;
  }
  template<class Lights>
  bool refresh(const Lights &lights){
    bool changed=false;
    for(unsigned i=0;i<card_light_count;++i){
      int level=std::max(0,lights.confirmed(i));
      if(int(i)!=drag_ && displayed_[i]!=level && row(i,level))changed=true;
    }
    return changed;
  }
  template<class Lights>
  bool touch(int x,int y,const Lights &lights){
    if(drag_<0){
      int index=controls_.hit(theme_,x,y);
      if(index<0 || lights.confirmed(index)<0)return false;
      drag_=index;
    }
    const int value=controls_.level(theme_,drag_,x);
    if(!row(drag_,value))return false;
    preview_=value;
    return true;
  }
  template<class Lights>
  bool release(Lights &lights){
    const int index=drag_,value=preview_;
    drag_=preview_=-1;
    if(index<0 || value<0 || lights.confirmed(index)<0)return false;
    if(value==lights.confirmed(index))return true;
    return lights.request(index,value);
  }
  void cancel(){drag_=preview_=-1;}
};
}
