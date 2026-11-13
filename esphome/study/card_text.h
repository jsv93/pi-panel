#pragma once
#include "card_art.h"
#include "card_fields.h"
#include "../text_renderer.h"
#include <iterator>
#include <utility>

namespace study {
class CardText {
  CardArt *art_ = nullptr;
  uint8_t *packed_ = nullptr;
  size_t capacity_ = 0;

  bool inflate(unsigned offset, unsigned bytes, uint8_t *out, size_t count){
    if(!bytes || !out)return false;
    if(bytes>capacity_){
      auto *p=static_cast<uint8_t*>(heap_caps_realloc(packed_,bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!p)return false;
      packed_=p;capacity_=bytes;
    }
    return art_->read(offset,packed_,bytes) &&
           tinfl_decompress_mem_to_mem(out,count,packed_,bytes,1)==count;
  }
  static const CardGlyph *find(int font,unsigned code){
    auto key=std::pair{font,code};
    auto *it=std::lower_bound(std::begin(card_glyphs),std::end(card_glyphs),key,
          [](const CardGlyph &g,const auto &wanted){return std::pair{g.font,g.code}<wanted;});
    return it!=std::end(card_glyphs) && it->font==font && it->code==code?it:nullptr;
  }
 public:
  bool attach(CardArt &art){
    if(!art.open(card_fields_path,card_fields_size,card_fields_sha))return false;
    art_=&art;return true;
  }
  bool paint(const CardField &f,const char *value,uint8_t *frame,uint8_t *work,size_t work_size){
    size_t bg_bytes=size_t(f.w)*f.h*2;
    if(!art_ || !frame || !value || bg_bytes>work_size || !inflate(f.bg,f.size,work,bg_bytes))return false;
    for(int y=0;y<f.h;++y)memcpy(frame+2*(720*(f.y+y)+f.x),work+2*y*f.w,2*f.w);
    const CardGlyph *line[128];
    unsigned count=0;
    int advance=0;
    const auto *fallback=find(f.font,'?');
    while(*value && count<std::size(line)){
      auto *glyph=find(f.font,next_code(value));
      if(!glyph)glyph=fallback;
      if(!glyph)return false;
      if(advance+glyph->advance>f.w*64 || (count+1==std::size(line) && *value)){
        auto *dots=find(f.font,0x2026);
        if(dots){
          while(count && advance+dots->advance>f.w*64){advance-=line[--count]->advance+f.spacing;}
          line[count++]=dots;advance+=dots->advance;
        }
        break;
      }
      line[count++]=glyph;advance+=glyph->advance+f.spacing;
    }
    int pen=f.align==1?(f.w*64-advance)/2:f.align==2?f.w*64-advance:0;
    for(unsigned i=0;i<count;++i){
      const auto &g=*line[i];
      int left=(pen+32)/64+g.x,top=f.baseline+g.y;
      pen+=g.advance+f.spacing;
      if(!g.size)continue;
      size_t bytes=size_t(g.w)*g.h;
      if(bytes>work_size || !inflate(g.offset,g.size,work,bytes))return false;
      for(int y=std::max(0,-top);y<g.h && y+top<f.h;++y){
        for(int x=std::max(0,-left);x<g.w && x+left<f.w;++x){
          unsigned alpha=work[y*g.w+x],inv=255-alpha;
          if(!alpha)continue;
          auto &p=reinterpret_cast<uint16_t*>(frame)[(f.y+top+y)*720+f.x+left+x];
          p=((((p>>11)*inv+(f.colour>>11)*alpha+127)/255)<<11) |
            (((((p>>5)&63)*inv+((f.colour>>5)&63)*alpha+127)/255)<<5) |
            (((p&31)*inv+(f.colour&31)*alpha+127)/255);
        }
      }
    }
    return true;
  }
};
}
