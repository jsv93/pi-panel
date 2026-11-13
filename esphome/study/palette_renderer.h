#pragma once
#include "../palette_assets.h"
#include "motion_tail.h"
#include "esp_partition.h"
#include "esp_heap_caps.h"
#include "mbedtls/sha256.h"
#include <algorithm>
#include <array>
#include <cstring>

extern "C" size_t tinfl_decompress_mem_to_mem(void *,size_t,const void *,size_t,int);
namespace study {
class PaletteRenderer {
  static constexpr int width=720,height=1280,page_bytes=width*height*2;
  struct Key {uint16_t colour,first;};
  struct Table {Key *keys=nullptr;uint16_t *colours=nullptr;size_t count=0,rows=0;};
  const uint8_t *data_=nullptr;
  esp_partition_mmap_handle_t mapping_{};
  std::array<Table,16> tables_;
  uint8_t *ranks_=nullptr;
  int selected_=0,page_=-1;
  bool expand(const PaletteSection &block,void *out,size_t capacity)const{
    return data_ && block.offset<=palette_size && block.size<=palette_size-block.offset && block.raw<=capacity &&
      tinfl_decompress_mem_to_mem(out,block.raw,data_+block.offset,block.size,1)==block.raw;
  }
 public:
  bool begin(const esp_partition_t *part){
    if(!part)return false;
    const void *data=nullptr;uint8_t digest[32];
    if(esp_partition_mmap(part,palette_offset,palette_size,ESP_PARTITION_MMAP_DATA,&data,&mapping_)!=ESP_OK)return false;
    if(mbedtls_sha256(static_cast<const uint8_t*>(data),palette_size,digest,0) || memcmp(digest,palette_sha,sizeof(digest))){
      esp_partition_munmap(mapping_);return false;
    }
    data_=static_cast<const uint8_t*>(data);return true;
  }
  bool available()const{return data_!=nullptr;}
  int selection()const{return selected_;}
  bool choose(int mode,uint8_t *temporary){
    if(mode<0 || mode>5 || !data_ || !temporary)return false;
    if(!mode){
      for(auto &table:tables_){heap_caps_free(table.keys);heap_caps_free(table.colours);table=Table{};}
      heap_caps_free(ranks_);ranks_=nullptr;selected_=0;page_=-1;return true;
    }
    if(mode==selected_)return true;
    if(!ranks_)ranks_=static_cast<uint8_t*>(heap_caps_malloc(width*height,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!ranks_)return false;
    for(size_t i=0;i<tables_.size();i++){
      const auto &block=palette_tables[i];
      if(block.raw<4 || !expand(block,temporary,page_bytes))return false;
      auto *values=reinterpret_cast<const uint16_t*>(temporary);
      const unsigned n=values[0],rows=values[1];
      if(!n || !rows || block.raw!=4+4*n+10*rows)return false;
      auto &table=tables_[i];
      if(!table.keys)table.keys=static_cast<Key*>(heap_caps_malloc(n*sizeof(Key),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!table.colours)table.colours=static_cast<uint16_t*>(heap_caps_malloc(2*rows,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!table.keys || !table.colours)return false;
      table.count=n;table.rows=rows;
      memcpy(table.keys,values+2,4*n);
      values+=2+2*n;
      for(unsigned j=0;j<rows;j++)table.colours[j]=values[j*5+mode-1];
    }
    page_=-1;selected_=mode;return true;
  }
  bool page(int index){
    if(!selected_ || page_==index)return true;
    if(index<0 || size_t(index)>=sizeof(palette_maps)/sizeof(palette_maps[0]) || !expand(palette_maps[index],ranks_,width*height))return false;
    page_=index;return true;
  }
  bool picker(uint8_t *out)const{return expand(palette_choices[selected_],out,page_bytes);}
  void label(uint16_t *frame,uint8_t *scratch)const{
    const auto &r=palette_buttons[0];
    if(!expand(palette_labels[selected_],scratch,page_bytes))return;
    for(int y=0;y<r.h;y++)memcpy(frame+(r.y+y)*width+r.x,scratch+2*y*r.w,2*r.w);
  }
  void render(uint16_t *frame,int x,int y,int w,int h,bool exact)const{
    if(!selected_)return;
    for(int row=y;row<y+h;row++)for(int column=x;column<x+w;column++){
      const unsigned position=row*width+column;
      auto &pixel=frame[position];
      const auto &t=tables_[(row%4)*4+column%4];
      auto end=t.keys+t.count;
      auto key=std::lower_bound(t.keys,end,pixel,[](const Key &k,uint16_t colour){return k.colour<colour;});
      if(key==end || key->colour!=pixel)continue;
      const size_t first=key->first,limit=key+1==end?t.rows:(key+1)->first;
      const size_t wanted=first+(exact && page_>=0?ranks_[position]:0);
      pixel=t.colours[wanted<limit?wanted:first];
    }
  }
};
}
