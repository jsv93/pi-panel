#pragma once
#include "popup_ground.h"
#include "esp_cache.h"
// Included after the native render state. Popup pixels remain lossless RGB565.
namespace study {
class PopupMotion {
  bool running_=false;
  int phase_=-1,frames_=0;
  int64_t started_=0;
  static constexpr int clip=1144;
  bool blend(uint8_t *out,int x,int span,int shift,unsigned opacity){
    if(!span)return true;
    ppa_blend_oper_config_t op{};
    op.in_bg.buffer=previous_pixels;op.in_bg.pic_w=width;op.in_bg.pic_h=height;
    op.in_bg.block_offset_x=x;op.in_bg.block_w=span;op.in_bg.block_h=clip;
    op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.in_fg=op.in_bg;op.in_fg.buffer=scratch;op.in_fg.block_offset_x=x-shift;
    op.out.buffer=out;op.out.buffer_size=page_bytes;op.out.pic_w=width;op.out.pic_h=height;
    op.out.block_offset_x=x;op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.bg_alpha_fix_val=255;
    op.fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.fg_alpha_fix_val=(opacity*255+16)/32;
    return ppa_do_blend(blender,&op)==ESP_OK;
  }
 public:
  bool active()const{return running_;}
  void cancel(){running_=false;}
  bool begin(Scanout::Slot *target,bool){
    if(!blender || !scanout.active || !scratch || !previous_pixels)return false;
    nav.cancel();scanout.copy_pixels(scratch,target->pixels,page_bytes);
    // CM5 overlays hide the parent sheet. Preserve only the palette ground
    // behind the incoming contents, with the navigation bar held stationary.
    const auto *pattern=popup_ground565[palette.selection()];
    auto *out=reinterpret_cast<uint32_t*>(previous_pixels);
    for(int y=0;y<clip;++y){
      const uint32_t a=pattern[(y&3)*4]|(uint32_t(pattern[(y&3)*4+1])<<16);
      const uint32_t b=pattern[(y&3)*4+2]|(uint32_t(pattern[(y&3)*4+3])<<16);
      for(int x=0;x<width/2;x+=2){*out++=a;*out++=b;}
    }
    esp_cache_msync(previous_pixels,clip*width*2,ESP_CACHE_MSYNC_FLAG_DIR_C2M);
    esp_cache_msync(scratch,page_bytes,ESP_CACHE_MSYNC_FLAG_DIR_C2M);
    phase_=-1;frames_=0;started_=clock_ms();running_=true;return true;
  }
  bool draw(){
    if(!running_)return true;
    int phase=std::min(10,int((clock_ms()-started_+9)/18));if(phase==9)phase=10;
    if(phase<=phase_)return false;
    auto *slot=scanout.acquire(false,true);if(!slot)return false;
    if(phase==10)scanout.copy_pixels(slot->pixels,scratch,page_bytes);
    else{
      const auto pose=nav_pose[0][phase];
      if(!blend(slot->pixels,pose.shift,width-pose.shift,pose.shift,pose.alpha) ||
         !blend(slot->pixels,0,pose.shift,0,pose.alpha)){
        scanout.copy_pixels(slot->pixels,scratch,page_bytes);phase=10;
      }
      if(slot->fixed_page!=revision)
        scanout.copy_pixels(slot->pixels+clip*width*2,scratch+clip*width*2,(height-clip)*width*2);
    }
    // PPA and DMA wrote the frame directly; no full-screen CPU writeback.
    if(!scanout.present(slot,0,1))return false;
    slot->page=phase==10?revision:0;slot->fixed_page=revision;slot->lamp_background=false;
    phase_=phase;++frames_;
    if(phase!=10)return false;
    running_=false;ESP_LOGI("study","Popup transition: %d frames in %lld ms",frames_,clock_ms()-started_);return true;
  }
};
static PopupMotion popup_motion;
static bool start_popup_motion(Scanout::Slot *target,bool ground){
  if(!popup_motion.begin(target,ground))return false;
  moving=true;return true;
}
}
