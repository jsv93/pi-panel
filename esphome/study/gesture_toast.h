#pragma once
#include "gesture_assets.h"
#include "driver/ppa.h"

namespace study {
// A small transient overlay. Its backdrop belongs to each retired scanout slot;
// never paint the live DMA buffer or bake a toast into a page/transition cache.
class GestureToast {
 public:
  static constexpr int left=180,top=532,w=360,h=216;
  void show(const char *message,int64_t now){
    if(!mask_)mask_=static_cast<uint8_t*>(heap_caps_calloc(w,h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!background_)background_=static_cast<uint8_t*>(heap_caps_calloc(w,h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!mask_ || !background_)return;
    if(!until_ || now>=until_+180)start_=now;
    until_=now+1400;dirty_=true;texture_dirty_=true;
    memset(mask_,0,w*h);
    const GestureGlyph *lines[4][80]{};int counts[4]{},advances[4]{},line=0;
    // CSS shrink-to-fit leaves 272 px of content inside the 44 px padding.
    const char *p=message;
    while(*p && line<4){
      const GestureGlyph *word[80];int count=0,advance=0;
      while(*p && *p!=' ' && count<80){const auto &g=glyph(next_code(p));word[count++]=&g;advance+=g.advance+32;}
      const auto &space=glyph(' ');const int gap=counts[line]?space.advance+32:0;
      if(counts[line] && advances[line]+gap+advance>272*64){if(++line==4)break;}
      else if(gap){lines[line][counts[line]++]=&space;advances[line]+=gap;}
      for(int i=0;i<count && counts[line]<80;i++)lines[line][counts[line]++]=word[i];
      advances[line]+=advance;while(*p==' ')++p;
    }
    line=std::min(line,3);int widest=0;for(int i=0;i<=line;i++)widest=std::max(widest,advances[i]);
    box_w_=line?360:std::min(360,(widest+63)/64+88);box_h_=52+41*(line+1);
    const int x0=(w-box_w_)/2,y0=(h-box_h_)/2;
    for(int y=0;y<h;y++)for(int x=0;x<w;x++){
      const int dx=std::max(x0+26-x,x-(x0+box_w_-27)),dy=std::max(y0+26-y,y-(y0+box_h_-27));
      int coverage=255;
      if(dx>0 && dy>0)coverage=std::clamp(int((26.5f-std::sqrt(float(dx*dx+dy*dy)))*255),0,255);
      else if(x<x0 || x>=x0+box_w_ || y<y0 || y>=y0+box_h_)coverage=0;
      background_[y*w+x]=coverage;
    }
    uint8_t scratch[2048];
    for(int row=0;row<=line;row++){
      int pen=(x0+44)*64;
      for(int i=0;i<counts[row];i++){
        const auto &g=*lines[row][i];const int x=(pen+32)/64+g.x,y=y0+26+33+row*41+g.y;pen+=g.advance+32;
        if(!g.size || size_t(g.w*g.h)>sizeof(scratch) || tinfl_decompress_mem_to_mem(scratch,g.w*g.h,gesture_alpha+g.offset,g.size,1)!=size_t(g.w*g.h))continue;
        for(int r=0;r<g.h;r++)for(int c=0;c<g.w;c++)if(x+c>=0 && x+c<w && y+r>=0 && y+r<h)mask_[(y+r)*w+x+c]=scratch[r*g.w+c];
      }
    }
  }
  bool active(int64_t now)const{return dirty_ || (until_ && now<until_+180);}
  bool animating(int64_t now)const{return dirty_ || (until_ && (now<start_+180 || now>=until_));}
  void restore(Scanout::Slot *slot){
    if(!slot->has_toast)return;
    for(int y=0;y<h;y++)memcpy(slot->pixels+2*((top+y)*720+left),slot->toast_background+2*y*w,2*w);
    slot->has_toast=false;
  }
  void __attribute__((optimize("O3"))) draw(Scanout::Slot *slot,int &first,int &end,int64_t now,int palette,ppa_client_handle_t blender){
    dirty_=false;
    if(!until_ || now>=until_+180){
      until_=0;
      heap_caps_free(rgba_);heap_caps_free(scaled_);rgba_=scaled_=nullptr;
      heap_caps_free(mask_);heap_caps_free(background_);mask_=background_=nullptr;
      return;
    }
    if(!slot->toast_background)slot->toast_background=static_cast<uint8_t*>(heap_caps_malloc(2*w*h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!slot->toast_background)return;
    for(int y=0;y<h;y++)memcpy(slot->toast_background+2*y*w,slot->pixels+2*((top+y)*720+left),2*w);
    slot->has_toast=true;first=std::min(first,top);end=std::max(end,top+h);
    const float opacity=now<until_?ease(std::min(1.f,(now-start_)/180.f)):1.f-ease(std::min(1.f,(now-until_)/180.f));
    const int a=std::lround(opacity*256),scale=std::lround((.9f+.1f*opacity)*65536);
    if(!rgba_)rgba_=static_cast<uint32_t*>(heap_caps_aligned_alloc(64,4*w*h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!scaled_)scaled_=static_cast<uint32_t*>(heap_caps_aligned_alloc(64,4*w*h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!rgba_ || !scaled_)return;
    const uint16_t ink=gesture_inks[std::clamp(palette,0,5)];
    if(texture_dirty_ || ink!=ink_){
      ink_=ink;texture_dirty_=false;
      const int red=(ink>>11)*255/31,green=((ink>>5)&63)*255/63,blue=(ink&31)*255/31;
      for(int i=0;i<w*h;i++){
        const int g=mask_[i],bg=background_[i]*235*(255-g)/65025,alpha=g+bg;
        const int r=alpha?(red*g+12*bg+alpha/2)/alpha:12;
        const int gr=alpha?(green*g+12*bg+alpha/2)/alpha:12;
        const int b=alpha?(blue*g+16*bg+alpha/2)/alpha:16;
        rgba_[i]=(uint32_t(alpha)<<24)|(r<<16)|(gr<<8)|b;
      }
    }
    const uint32_t *foreground=rgba_;
    if(scale!=65536){
      int xs[w];for(int x=0;x<w;x++)xs[x]=((x-w/2)*65536LL*256/scale)+w*128;
      for(int y=0;y<h;y++){
        const int sy=((y-h/2)*65536LL*256/scale)+h*128,iy=sy>>8,fy=sy&255;
        for(int x=0;x<w;x++){
          const int sx=xs[x],ix=sx>>8,fx=sx&255;
          uint32_t pixel=0x000c0c10;
          if(ix>=0 && iy>=0 && ix<w-1 && iy<h-1){
            const auto upper=mix(rgba_[iy*w+ix],rgba_[iy*w+ix+1],fx);
            const auto lower=mix(rgba_[(iy+1)*w+ix],rgba_[(iy+1)*w+ix+1],fx);
            pixel=mix(upper,lower,fy);
          }
          scaled_[y*w+x]=pixel;
        }
      }
      foreground=scaled_;
    }
    ppa_blend_oper_config_t op{};
    op.in_bg.buffer=slot->pixels;op.in_bg.pic_w=720;op.in_bg.pic_h=1280;
    op.in_bg.block_w=w;op.in_bg.block_h=h;op.in_bg.block_offset_x=left;op.in_bg.block_offset_y=top;op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.in_fg.buffer=foreground;op.in_fg.pic_w=w;op.in_fg.pic_h=h;
    op.in_fg.block_w=w;op.in_fg.block_h=h;op.in_fg.blend_cm=PPA_BLEND_COLOR_MODE_ARGB8888;
    op.out.buffer=slot->pixels;op.out.buffer_size=720*1280*2;op.out.pic_w=720;op.out.pic_h=1280;
    op.out.block_offset_x=left;op.out.block_offset_y=top;op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.bg_alpha_fix_val=255;
    op.fg_alpha_update_mode=a==256?PPA_ALPHA_NO_CHANGE:PPA_ALPHA_SCALE;
    op.fg_alpha_scale_ratio=std::clamp(a/256.f,1.f/256.f,255.f/256.f);
    if(a>0 && ppa_do_blend(blender,&op)!=ESP_OK)ESP_LOGW("study","Gesture overlay unavailable");
  }

 private:
  uint8_t *mask_=nullptr,*background_=nullptr;
  uint32_t *rgba_=nullptr,*scaled_=nullptr;bool texture_dirty_=true;uint16_t ink_=0;int box_w_=0,box_h_=0;int64_t start_=0,until_=0;bool dirty_=false;
  static const GestureGlyph &glyph(unsigned code){
    for(const auto &g:gesture_glyphs)if(g.code==code)return g;
    for(const auto &g:gesture_glyphs)if(g.code=='?')return g;
    return gesture_glyphs[0];
  }
  static float ease(float t){
    if(t<=0)return 0;if(t>=1)return 1;
    float lo=0,hi=1;for(int i=0;i<12;i++){const float u=(lo+hi)/2,v=1-u;if(3*v*v*u*.22f+3*v*u*u*.36f+u*u*u<t)lo=u;else hi=u;}
    const float u=(lo+hi)/2,v=1-u;return 3*v*v*u*.61f+3*v*u*u+u*u*u;
  }
  static inline __attribute__((always_inline)) uint32_t mix(uint32_t a,uint32_t b,int t){
    const uint32_t u=256-t;
    const uint32_t rb=(((a&0x00ff00ff)*u+(b&0x00ff00ff)*t)>>8)&0x00ff00ff;
    const uint32_t ag=((((a>>8)&0x00ff00ff)*u+((b>>8)&0x00ff00ff)*t))&0xff00ff00;
    return rb|ag;
  }
};
}
