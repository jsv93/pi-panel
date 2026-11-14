#pragma once
#include "card_art.h"
#include "card_fields.h"
#if __has_include("card_numbers.h")
#include "card_numbers.h"
#define STUDY_CARD_CLIMATE
#endif
#include "../text_renderer.h"
#include <iterator>
#include <utility>

namespace study {
class CardText {
  CardArt *art_ = nullptr;
  const CardGlyph *begin_=nullptr,*end_=nullptr;
  CardGlyph *owned_=nullptr;
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
  const CardGlyph *find(int font,unsigned code)const{
    auto key=std::pair{font,code};
    auto *it=std::lower_bound(begin_,end_,key,
          [](const CardGlyph &g,const auto &wanted){return std::pair{g.font,g.code}<wanted;});
    return it!=end_ && it->font==font && it->code==code?it:nullptr;
  }
 public:
  bool attach(CardArt &art){
    if(!art.open(card_fields_path,card_fields_size,card_fields_sha))return false;
#ifdef STUDY_CARD_EXTERNAL_GLYPHS
    return use_bank(art,card_glyph_offset,card_glyph_count);
#else
    begin_=card_glyphs;end_=card_glyphs+std::size(card_glyphs);
    art_=&art;return true;
#endif
  }
  bool use_bank(CardArt &art,unsigned offset,unsigned count){
    static_assert(sizeof(CardGlyph)==36);
    const size_t bytes=count*sizeof(CardGlyph);
    if(owned_ && art_==&art)return true;
    auto *table=static_cast<CardGlyph*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!table || !art.read(offset,table,bytes)){heap_caps_free(table);return false;}
    heap_caps_free(owned_);owned_=table;
    art_=&art;begin_=table;end_=table+count;return true;
  }
  bool background(const CardField &f,uint8_t *frame,uint8_t *work,size_t work_size){
    size_t bg_bytes=size_t(f.w)*f.h*2;
    if(!art_ || !frame || bg_bytes>work_size || !inflate(f.bg,f.size,work,bg_bytes))return false;
    for(int y=0;y<f.h;++y)memcpy(frame+2*(720*(f.y+y)+f.x),work+2*y*f.w,2*f.w);
    return true;
  }
  bool paint(const CardField &f,const char *value,uint8_t *frame,uint8_t *work,size_t work_size){
    if(!value || !background(f,frame,work,work_size))return false;
    return write(f,value,frame,work,work_size,0,1280);
  }
  template<class Field> bool write(const Field &f,const char *value,uint8_t *frame,uint8_t *work,size_t work_size,int clip_top,int clip_end){
    if(f.y+f.h<=clip_top || f.y>=clip_end)return true;
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
      if(!g.size || f.y+top+g.h<=clip_top || f.y+top>=clip_end)continue;
      size_t bytes=size_t(g.w)*g.h;
      if(bytes>work_size || !inflate(g.offset,g.size,work,bytes))return false;
      for(int y=std::max({0,-top,clip_top-f.y-top});y<g.h && y+top<f.h && f.y+top+y<clip_end;++y){
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
#ifdef STUDY_CARD_CLIMATE
  bool reading(const CardField &f,const char *text,uint8_t *frame,uint8_t *work,size_t capacity){
    if(!background(f,frame,work,capacity))return false;
    int pen=0;
    for(size_t i=0;;++i){
      const char c=text[i];
      int idx=c==0?13:c=='~'?12:c=='-'?11:c=='.'?10:c-'0';
      if(idx<0 || idx>13)return false;
      const auto &g=card_digits[f.theme][f.id==FieldId::cHum][idx];
      const size_t size=size_t(g.w)*g.h;
      if(size>capacity || tinfl_decompress_mem_to_mem(work,size,card_digit_alpha+g.offset,g.size,1)!=size)return false;
      const int left=(pen+32)/64+g.x;
      for(int y=0;y<g.h && g.y+y<f.h;++y)for(int x=0;x<g.w && left+x<f.w;++x){
        const unsigned a=work[y*g.w+x],b=255-a;
        if(!a)continue;
        auto &p=reinterpret_cast<uint16_t*>(frame)[(f.y+g.y+y)*720+f.x+left+x];
        p=(((((p>>11)*b+(f.colour>>11)*a+127)/255)<<11) |
            (((((p>>5)&63)*b+((f.colour>>5)&63)*a+127)/255)<<5) |
            (((p&31)*b+(f.colour&31)*a+127)/255));
      }
      if(!c)break;
      pen+=g.advance;
    }
    return true;
  }
#endif
};
}
