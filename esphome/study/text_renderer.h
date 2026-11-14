#pragma once
#include "text_art.h"
#include <algorithm>
#include <cstring>
extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);
#ifdef STUDY_OVERLAY_PALETTES
#include "live_runtime/overlay_artwork.h"
#endif

namespace study {
static bool text_image(uint8_t *out,size_t count,uint32_t offset,uint32_t size){
#ifdef STUDY_OVERLAY_PALETTES
  if(text_palette>=0)return overlay_artwork.expand(offset,size,text_palette,out,count);
#endif
  return tinfl_decompress_mem_to_mem(out,count,text_art+offset,size,1)==count;
}
static const TextGlyph &text_glyph(int font,unsigned code){
  const auto *begin=text_glyphs+text_starts[font],*end=text_glyphs+text_starts[font+1];
  auto find=[&](unsigned cp){return std::lower_bound(begin,end,cp,[](const TextGlyph &g,unsigned c){return g.code<c;});};
  const auto *g=find(code);
  return g!=end && g->code==code?*g:*find('?');
}
static unsigned next_code(const char *&p){
  const unsigned first=static_cast<uint8_t>(*p++);
  if(first<128)return first;
  int count=first>=0xf0?3:first>=0xe0?2:first>=0xc0?1:0;
  unsigned code=first&(count==3?7:count==2?15:31);
  while(count--){if((static_cast<uint8_t>(*p)&0xc0)!=0x80)return '?';code=(code<<6)|(static_cast<uint8_t>(*p++)&63);}
  return code;
}
static void text_background(uint8_t *page_pixels,int width,uint8_t *scratch,const Rect &r,uint32_t offset,uint32_t size){
  const size_t bytes=2*r.w*r.h;
  if(!text_image(scratch,bytes,offset,size))return;
  for(int y=0;y<r.h;y++)memcpy(page_pixels+2*((r.y+y)*width+r.x),scratch+2*y*r.w,2*r.w);
}
static void text_field(uint8_t *page_pixels,int width,uint8_t *scratch,const TextArea &f,const char *value,int clip_top=0,int clip_end=1280,bool restore_background=true){
  const auto &r=f.rect;
  uint16_t colour=f.colour;
#ifdef STUDY_OVERLAY_PALETTES
  if(text_palette>=0)colour=overlay_artwork.colour(f.bg,f.size,f.colour,f.font,text_palette);
#endif
  if(r.y>=clip_end || r.y+r.h<=clip_top)return;
  if(restore_background && r.y>=clip_top && r.y+r.h<=clip_end)text_background(page_pixels,width,scratch,r,f.bg,f.size);
  const TextGlyph *line[128];
  int count=0,advance=0;
  while(*value && count<128){
    const auto &g=text_glyph(f.font,next_code(value));line[count++]=&g;
    advance+=g.advance+f.spacing;
    if(advance>r.w*64 || (count==128 && *value)){
      const auto &ellipsis=text_glyph(f.font,0x2026);
      while(count && (advance+ellipsis.advance>r.w*64 || count==128))advance-=line[--count]->advance+f.spacing;
      line[count++]=&ellipsis;advance+=ellipsis.advance;break;
    }
  }
  int pen=f.align==1?(r.w*64-advance)/2:f.align==2?r.w*64-advance:0;
  for(int i=0;i<count;i++){
    const auto &g=*line[i];
    const int left=(pen+32)/64+g.x,top=f.baseline+g.y;
    pen+=g.advance+f.spacing;
    if(!g.size || r.y+top>=clip_end || r.y+top+g.h<=clip_top)continue;
    if(tinfl_decompress_mem_to_mem(scratch,g.w*g.h,text_art+g.offset,g.size,1)!=size_t(g.w*g.h))continue;
    for(int y=std::max({0,-top,clip_top-r.y-top});y<g.h && top+y<r.h && r.y+top+y<clip_end;y++)for(int x=std::max(0,-left);x<g.w && left+x<r.w;x++){
      const unsigned a=scratch[y*g.w+x],b=255-a;if(!a)continue;
      auto &px=reinterpret_cast<uint16_t*>(page_pixels)[(r.y+top+y)*width+r.x+left+x];
      px=((((px>>11)*b+(colour>>11)*a+127)/255)<<11)|
         (((((px>>5)&63)*b+((colour>>5)&63)*a+127)/255)<<5)|
         (((px&31)*b+(colour&31)*a+127)/255);
    }
  }
}
}
