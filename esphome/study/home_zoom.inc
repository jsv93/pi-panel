#pragma once
// Included by navigation.h after the native page/number definitions. The .inc
// suffix stops ESPHome's directory importer from including it before study.h.
#include "home_zoom_assets.h"
#include "card_art.h"
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include "../study_lz4/lz4.h"

namespace study {
class HomeZoomArtwork {
  CardArt file_;
  std::atomic<int> state_{0};
  std::atomic<uint32_t> retry_at_{0};
  uint8_t *mask_=nullptr,*glyph_=nullptr;
  uint16_t *shade_=nullptr;
#ifdef STUDY_HOME_LZ4
  uint8_t *packed_=nullptr;
#endif
  int shade_mode_=-1;
  bool player_visible_=false;
  static constexpr size_t glyph_capacity=8192;
  bool load(){
    if(!file_.mount() || !file_.open(home_zoom_path,home_zoom_size,home_zoom_sha))return false;
#ifdef STUDY_HOME_LZ4
    if(!packed_)packed_=static_cast<uint8_t*>(heap_caps_malloc(home_zoom_max_stored,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!packed_)return false;
#endif
    const auto &r=number_rects[0];
    if(!mask_)mask_=static_cast<uint8_t*>(heap_caps_malloc(r.w*r.h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!glyph_)glyph_=static_cast<uint8_t*>(heap_caps_malloc(glyph_capacity,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!shade_)shade_=static_cast<uint16_t*>(heap_caps_malloc(2*home_strip.w*home_strip.h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    return mask_ && glyph_ && shade_;
  }
  static uint16_t mix(uint16_t bg,uint16_t fg,unsigned alpha){
    const unsigned b=255-alpha;
    return ((((bg>>11)*b+(fg>>11)*alpha+127)/255)<<11) |
      (((((bg>>5)&63)*b+((fg>>5)&63)*alpha+127)/255)<<5) |
      (((bg&31)*b+(fg&31)*alpha+127)/255);
  }
  unsigned alpha(int x,int y)const{
    const auto &r=number_rects[0];
    return x>=0 && y>=0 && x<r.w && y<r.h?mask_[y*r.w+x]:0;
  }
 public:
  bool ready()const{return state_.load()==2;}
  void warm(){
    if(ready())return;
    const uint32_t now=esp_timer_get_time()/1000,retry=retry_at_.load();
    if(retry && int32_t(now-retry)<0)return;
    int idle=0;if(!state_.compare_exchange_strong(idle,1))return;
    if(xTaskCreate([](void *context){
        auto &self=*static_cast<HomeZoomArtwork*>(context);
        const bool loaded=self.load();
        if(!loaded)self.retry_at_.store(uint32_t(esp_timer_get_time()/1000)+30000);
        self.state_.store(loaded?2:0);
        ESP_LOGI("study","Home zoom artwork %s",loaded?"ready":"unavailable");
        vTaskDelete(nullptr);
      },"study_home_art",8192,this,1,nullptr)!=pdPASS){
      retry_at_.store(now+30000);state_.store(0);
    }
  }
  unsigned frame_size(unsigned palette,unsigned phase)const{
#ifdef STUDY_HOME_LZ4
    return ready() && palette<6 && phase<10?home_zoom_frames[palette*10+phase][2]:0;
#else
    return ready() && palette<6 && phase<10?home_zoom_frames[palette*10+phase][1]:0;
#endif
  }
  bool frame(unsigned palette,unsigned phase,uint8_t *destination,size_t capacity){
    const auto bytes=frame_size(palette,phase);
#ifdef STUDY_HOME_LZ4
    if(!bytes || bytes>capacity)return false;
    const auto &frame=home_zoom_frames[palette*10+phase];
    return frame[1]<=home_zoom_max_stored && file_.read(frame[0],packed_,frame[1]) &&
      LZ4_decompress_safe(reinterpret_cast<const char*>(packed_),reinterpret_cast<char*>(destination),frame[1],bytes)==int(bytes);
#else
    return bytes && bytes<=capacity && file_.read(home_zoom_frames[palette*10+phase][0],destination,bytes);
#endif
  }
  void prepare(int mode,float temperature,bool playing){
    if(!ready())return;
    player_visible_=playing;
    if(shade_mode_!=mode){std::fill_n(shade_,home_strip.w*home_strip.h,home_zoom_scrims[mode]);shade_mode_=mode;}
    const auto &r=number_rects[0];memset(mask_,0,r.w*r.h);
    char text[24];
    if(std::isfinite(temperature))snprintf(text,sizeof(text),"%.1f",double(temperature));else strcpy(text,"~");
    int pen=0;
    for(size_t i=0;i<=strlen(text);++i){
      const char c=text[i];const int index=c==0?13:c=='~'?12:c=='-'?11:c=='.'?10:c-'0';
      if(index<0 || index>=14)continue;
      const auto &g=number_glyphs[0][index];
      if(g.size && size_t(g.w*g.h)<=glyph_capacity &&
         tinfl_decompress_mem_to_mem(glyph_,g.w*g.h,control_art+g.pos,g.size,1)==size_t(g.w*g.h)){
        for(int y=0;y<g.h;++y)for(int x=0;x<g.w;++x){
          const int px=(pen+32)/64+g.x+x,py=g.y+y;
          if(px>=0 && py>=0 && px<r.w && py<r.h)mask_[py*r.w+px]=std::max(mask_[py*r.w+px],glyph_[y*g.w+x]);
        }
      }
      pen+=g.advance;
    }
  }
  void draw(uint16_t *out,const uint8_t *foreground,int mode,int phase,int &first_y,int &end_y)const{
    const unsigned clear=255-home_zoom_opacities[phase];
    if(player_visible_){
      const auto &r=home_strip;
      ppa_blend_oper_config_t op{};
      op.in_bg.buffer=shade_;op.in_bg.pic_w=r.w;op.in_bg.pic_h=r.h;
      op.in_bg.block_w=r.w;op.in_bg.block_h=r.h;op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
      op.in_fg=op.in_bg;op.in_fg.buffer=foreground;op.in_fg.pic_w=width;op.in_fg.pic_h=height;
      op.in_fg.block_offset_x=r.x;op.in_fg.block_offset_y=r.y;
      op.out.buffer=out;op.out.buffer_size=page_bytes;op.out.pic_w=width;op.out.pic_h=height;
      op.out.block_offset_x=r.x;op.out.block_offset_y=r.y;op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
      op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.bg_alpha_fix_val=255;
      op.fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.fg_alpha_fix_val=clear;
      if(ppa_do_blend(blender,&op)!=ESP_OK){
        auto *fg=reinterpret_cast<const uint16_t*>(foreground);
        for(int y=r.y;y<r.y+r.h;++y)for(int x=r.x;x<r.x+r.w;++x)
          out[y*width+x]=mix(home_zoom_scrims[mode],fg[y*width+x],clear);
        first_y=std::min(first_y,r.y);end_y=std::max(end_y,r.y+r.h);
      }
    }
    // Only the temperature glyph mask scales. The photograph, player and
    // navigation stay fixed, exactly as their separate CM5 DOM layers do.
    const auto &r=number_rects[0];
    const int32_t scale=home_zoom_scales[phase],inverse=int32_t((int64_t(1)<<32)/scale);
    const int left=std::max(0,int((int64_t(r.x-width/2)*scale>>16)+width/2)-1);
    const int top=std::max(0,int((int64_t(r.y-height/2)*scale>>16)+height/2)-1);
    const int right=std::min(width,int((int64_t(r.x+r.w-width/2)*scale>>16)+width/2)+2);
    const int bottom=std::min(height,int((int64_t(r.y+r.h-height/2)*scale>>16)+height/2)+2);
    const uint16_t colour=mix(home_zoom_scrims[mode],home_zoom_inks[mode],clear);
    const int32_t start_x=int32_t(((int64_t(left-width/2)*65536+32768)*inverse>>16)+(width/2-r.x)*65536-32768);
    int32_t sy=int32_t(((int64_t(top-height/2)*65536+32768)*inverse>>16)+(height/2-r.y)*65536-32768);
    for(int y=top;y<bottom;++y,sy+=inverse){
      const int iy=sy>>16;const unsigned fy=(sy>>8)&255;
      int32_t sx=start_x;
      for(int x=left;x<right;++x,sx+=inverse){
        const int ix=sx>>16;const unsigned fx=(sx>>8)&255;
        const unsigned a=((alpha(ix,iy)*(256-fx)+alpha(ix+1,iy)*fx)*(256-fy)+
                          (alpha(ix,iy+1)*(256-fx)+alpha(ix+1,iy+1)*fx)*fy+32768)>>16;
        if(a)out[y*width+x]=mix(out[y*width+x],colour,a);
      }
    }
    first_y=std::min(first_y,top);end_y=std::max(end_y,bottom);
  }
};
static HomeZoomArtwork home_zoom_artwork;
}
