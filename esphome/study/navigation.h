#pragma once
#include "navigation_assets.h"
#include "motion_chunks.h"
#include "esp_partition.h"
#include "esp_rom_crc.h"
#ifdef STUDY_SD_NAVIGATION
#include "live_runtime/navigation_art.h"
#endif
#ifdef STUDY_HOME_ZOOM
#include "live_runtime/home_zoom.inc"
#endif
#ifdef STUDY_LIVE
#include "live_runtime/motion_tail.h"
#include "mbedtls/sha256.h"
#endif

namespace study {
#ifdef STUDY_LIVE
static const uint8_t *run_data;
#else
static const auto *run_data=chunk_data;
#endif
// In IDF 5.5 the RGB565 "BGR" setting emits little-endian pixels. "RGB"
// enables a DMA byte swap. The DSI scanout and native page sprites use LE.
constexpr auto panel_jpeg_order=JPEG_DEC_RGB_ELEMENT_ORDER_BGR;
static int color_error(uint16_t x,uint16_t y){
  return std::max({2*std::abs(int(x>>11)-int(y>>11)),
                   std::abs(int((x>>5)&63)-int((y>>5)&63)),
                   2*std::abs(int(x&31)-int(y&31))});
}
static jpeg_decoder_handle_t decoder(){
  static jpeg_decoder_handle_t handle;
  if(!handle){
    jpeg_decode_engine_cfg_t cfg{};cfg.timeout_ms=150;
    if(jpeg_new_decoder_engine(&cfg,&handle)!=ESP_OK)return nullptr;
  }
  return handle;
}

class Navigation {
  static constexpr int blocks=(width/16)*(height/16);
  static constexpr int paths=sizeof(nav_paths)/sizeof(nav_paths[0]);
  struct Cached {uint8_t *frames[10]{};};
  Cached cache_[paths]{};
  const uint8_t *header_{},*entropy_{},*maps_{};
  const uint32_t *offsets_{};
#ifdef STUDY_PACKED_SEGMENTS
  const uint8_t *segment_lengths_{};
#endif
  esp_partition_mmap_handle_t mapping_{};
  uint8_t *input_{},*arena_{},*writing_{};
  size_t input_size_{},arena_size_{},used_{};
  uint32_t *prepare_ids_{},*play_ids_{};
  uint8_t *chunks_{};
  uint32_t *chunk_offsets_{};
  uint16_t prepare_chunks_[blocks/8],play_chunks_[blocks/8];
  // Rebuild the optional run cache between input events when a palette
  // releases and later returns its memory to Architectural.
  int warm_chunk_=-1;
  size_t warm_bytes_=0;
  bool chunks_ready_=false;
  int owner_=-1,route_=-1,phase_=-1,prepare_route_=0,prepare_phase_=0,part_=0;
  int clip_{};
  bool from_variant_{},to_variant_{};
  int mode_=0,reference_mode_=0;
  bool sd_active_=false,sd_memory_=false;
  bool home_zoom_=false;
  uint16_t *fade_background_=nullptr;
  int fade_background_mode_=-1;
  bool warm_fade_background(int mode){
#ifdef STUDY_SD_NAVIGATION
    if(!sd_navigation_theme_fade)return false;
    if(!fade_background_ && heap_caps_get_free_size(MALLOC_CAP_SPIRAM)>page_bytes+2*1024*1024)
      fade_background_=static_cast<uint16_t*>(heap_caps_malloc(page_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!fade_background_)return false;
    if(fade_background_mode_!=mode){
      const uint32_t pixel=sd_navigation_backgrounds[mode];
      std::fill_n(reinterpret_cast<uint32_t*>(fade_background_),page_bytes/4,pixel|(pixel<<16));
      fade_background_mode_=mode;
    }
    return true;
#else
    return false;
#endif
  }
  // Source geometry for each eight-line strip. Pixel blending still uses
  // the exact tile intersections for the phase's sub-tile translation.
  static constexpr int tile_columns=width/16;
  static_assert(tile_columns+2<64);
  uint64_t overlay_rows_[doorbell+1][height/8]{};
  uint64_t changed_rows_[2][height/8]{};
  uint32_t *reference_hashes_[doorbell+1]{};
  struct LivePatch {
    uint16_t *pixels{};
    size_t capacity=0;
    uint64_t rows[height/8]{};
    int phase=-1;
  } patches_[2];
  LivePatch *play_patch_=&patches_[0],*next_patch_=&patches_[1];
  static constexpr size_t patch_pixels=128*1024;
  static uint32_t tile_hash(const uint8_t *pixels,int x,int y){
    uint32_t hash=0;
    for(int row=y;row<y+8;++row)
      hash=esp_rom_crc32_le(hash,pixels+2*(row*width+x),32);
    return hash;
  }
  // Record the immutable artwork once. Live text, covers and controls then
  // blend only tiles whose pixels actually differ from the baked animation.
  void remember_tiles(int mode=0){
    reference_mode_=-1;
    for(int page=home;page<doorbell;++page){
      size_t count=0;
      for(auto row:overlay_rows_[page])count+=__builtin_popcountll(row);
      if(!count)continue;
      auto *hashes=reference_hashes_[page];
      if(!hashes)hashes=static_cast<uint32_t*>(heap_caps_malloc(count*sizeof(uint32_t),MALLOC_CAP_SPIRAM));
      if(!hashes)return;
      reference_hashes_[page]=hashes;
#ifdef STUDY_SD_NAVIGATION
      if(navigation_artwork.ready()){
        auto *tiles=reinterpret_cast<uint32_t*>(scratch);
        if(!navigation_artwork.hashes(mode,page,tiles))return;
        for(int y=0;y<height;y+=8)
          for(auto bits=overlay_rows_[page][y/8];bits;bits&=bits-1)
            *hashes++=tiles[(y/8)*tile_columns+__builtin_ctzll(bits)];
        continue;
      }
#endif
      const uint8_t *reference=page==home?room_pixels:page==lights?lights_pixels:nullptr;
      if(!reference){
        if(!unpack(pages[page],scratch))return;
        reference=scratch;
      }
      for(int y=0;y<height;y+=8)
        for(auto bits=overlay_rows_[page][y/8];bits;bits&=bits-1)
          *hashes++=tile_hash(reference,16*__builtin_ctzll(bits),y);
      esphome::App.feed_wdt();
    }
    reference_mode_=mode;
  }
  void find_changes(int page,const uint8_t *live,uint64_t *rows)const{
    memcpy(rows,overlay_rows_[page],sizeof(changed_rows_[0]));
    if(reference_mode_!=mode_)return;
    auto *hashes=reference_hashes_[page];
    if(!hashes)return;
    for(int y=0;y<height;y+=8){
      for(auto bits=rows[y/8];bits;bits&=bits-1){
        const int x=16*__builtin_ctzll(bits);
        if(tile_hash(live,x,y)==*hashes++)rows[y/8]&=~(bits & -bits);
      }
    }
  }
  int64_t tap_at_{},first_at_{};
  TaskHandle_t producer_{};
  SemaphoreHandle_t ready_{};
  uint8_t *next_input_{};
  int queued_=-1;
  bool job_ok_=false,job_done_=false;
  const uint8_t *foreground_pixels()const{return palette_motion?scratch:page_pixels;}
  const uint8_t *background_pixels()const{
    return theme_fade() && fade_background_ && fade_background_mode_==mode_
      ?reinterpret_cast<const uint8_t*>(fade_background_):previous_pixels;
  }
  static bool variant(int p){
#ifdef STUDY_LIVE
    if(p>=home && p<=members_page)return true;
#endif
    if(p==scenes)return scene>=0;
    int i=p-light0;
    return i>=0 && i<light_count && levels[i]!=initial[i];
  }
  static bool affected(int page,int x,int y,bool include_player=false){
#ifdef STUDY_LIVE
    auto intersects=[=](const Rect &r){
      return x<r.x+r.w && x+16>r.x && y<r.y+r.h && y+8>r.y;
    };
    if(page==home)return intersects(number_rects[0]) || ((include_player || player().playing) && intersects(home_strip));
    if(page==room_menu_page)return intersects(menu_date.rect);
    if(page==settings_page)return intersects(mini_choice.rect);
    if(page==diagnostics_page || page==edit_page || page==members_page)return true;
    if(page==media)return intersects(transport_buttons[0]) || intersects(transport_buttons[2]) || intersects(transport_buttons[4]) ||
                         intersects(song_title.rect) || intersects(song_artist.rect) || intersects(volume_button) ||
                         intersects(album_rect) || intersects(seek_background) || intersects(elapsed_time.rect) || intersects(total_time.rect);
    if(page==display_page)return intersects(backlight_rail) || intersects(backlight_value);
    if(page==climate_page)return intersects(number_rects[1]) || intersects(number_rects[2]) ||
        intersects(number_rects[3]) || intersects(climate_slider) || intersects(climate_up) || intersects(climate_down);
    if(page==lights){
      for(int i=0;i<light_count;i++)if(intersects(row_values[i]) || intersects(row_powers[i]))return true;
      return intersects(all_lights_button);
    }
    if(page>=light0 && page<light0+light_count &&
       (intersects(detail_power_button) || intersects(slider_paint)))return true;
#endif
    int start=std::max(0,x),end=std::min(width,x+16);
    if(start>=end)return false;
    auto *bits=page==scenes?scene_changes:lamp_changes;
    for(int i=start/16;i<=(end-1)/16;i++){
      int bit=y/8*(width/16)+i;
      if(bits[bit/8] & (1u<<(bit%8)))return true;
    }
    return false;
  }
  Rect album_area(int shift)const{
#ifdef STUDY_LIVE
    const auto &path=nav_paths[route_];
    if(path.from!=media && path.to!=media)return {};
    const int left=std::max(std::max(0,shift),(album_rect.x+std::min(0,shift))/16*16);
    const int right=std::min(std::min(width,width+shift),(album_rect.x+album_rect.w+std::max(0,shift)+15)/16*16);
    const int top=album_rect.y/8*8,bottom=std::min(clip_,(album_rect.y+album_rect.h+7)/8*8);
    if(left<right && top<bottom)return {left,top,right-left,bottom-top};
#endif
    return {};
  }
  bool blend_region(uint16_t *out,const Rect &paint,int shift,unsigned alpha)const{
    ppa_blend_oper_config_t op{};
    op.in_bg.buffer=background_pixels();op.in_bg.pic_w=width;op.in_bg.pic_h=height;
    op.in_bg.block_offset_x=paint.x;op.in_bg.block_offset_y=paint.y;
    op.in_bg.block_w=paint.w;op.in_bg.block_h=paint.h;op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.in_fg=op.in_bg;op.in_fg.buffer=foreground_pixels();op.in_fg.block_offset_x=paint.x-shift;
    op.out.buffer=out;op.out.buffer_size=page_bytes;op.out.pic_w=width;op.out.pic_h=height;
    op.out.block_offset_x=paint.x;op.out.block_offset_y=paint.y;op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
    op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.bg_alpha_fix_val=255;
    op.fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.fg_alpha_fix_val=(alpha*255+16)/32;
    return ppa_do_blend(blender,&op)==ESP_OK;
  }
  bool blend_album(uint16_t *out,int shift,unsigned alpha,Rect &paint)const{
    paint=album_area(shift);
    return paint.w && blend_region(out,paint,shift,alpha);
  }
  bool blend_live_regions(uint16_t *out,const Pose &pose)const{
    for(int y=0;y<height;){
      auto tiles=dirty_tiles(y,pose);
      int bottom=y+8;
      while(bottom<height && dirty_tiles(bottom,pose)==tiles)bottom+=8;
      while(tiles){
        int x;const int span=take_span(tiles,x);
        const int motion_bottom=std::min(bottom,clip_);
        if(y<motion_bottom){
          const int left=std::clamp(pose.shift,x,x+span);
          const int right=std::clamp(width+pose.shift,x,x+span);
          if(left>x && !blend_region(out,{x,y,left-x,motion_bottom-y},0,0))return false;
          if(right<x+span && !blend_region(out,{right,y,x+span-right,motion_bottom-y},0,0))return false;
          if(right>left && !blend_region(out,{left,y,right-left,motion_bottom-y},pose.shift,pose.alpha))return false;
        }
        const int fixed_top=std::max(y,clip_);
        if(bottom>fixed_top && !blend_region(out,{x,fixed_top,span,bottom-fixed_top},0,32))return false;
      }
      y=bottom;
    }
    return true;
  }
  static void IRAM_ATTR __attribute__((optimize("O3"))) blend_span(
      uint16_t *__restrict out,const uint16_t *__restrict old,
      const uint16_t *__restrict next,int count,unsigned a){
    const unsigned b=32-a;
    for(int i=0;i<count;++i){
      const unsigned p=old[i],q=next[i];
      out[i]=((((p&0xf81f)*b+(q&0xf81f)*a)>>5)&0xf81f) |
             ((((p&0x07e0)*b+(q&0x07e0)*a)>>5)&0x07e0);
    }
  }
  uint64_t dirty_tiles(int y,const Pose &pose)const{
    uint64_t tiles=from_variant_ && y<clip_?changed_rows_[0][y/8]:0;
    if(to_variant_){
      const auto base=changed_rows_[1][y/8];
      const unsigned distance=unsigned(std::abs(pose.shift)),whole=distance/16;
      const auto shifted=pose.shift>=0?base<<whole:base>>whole;
      tiles|=shifted;
      if(distance%16)tiles|=pose.shift>=0?shifted<<1:shifted>>1;
      if(y+8>clip_)tiles|=base;
    }
    return tiles&((uint64_t(1)<<tile_columns)-1);
  }
  static bool inside_album(const Rect &album,int x,int y){
    return album.w && x>=album.x && x+16<=album.x+album.w && y>=album.y && y+8<=album.y+album.h;
  }
  static int take_span(uint64_t &tiles,int &x){
    const int first=__builtin_ctzll(tiles);
    const int count=__builtin_ctzll(~(tiles>>first));
    tiles&=~(((uint64_t(1)<<count)-1)<<first);
    x=first*16;
    return count*16;
  }
  void paint_span(uint16_t *out,int stride,int x,int y,int span,const Pose &pose)const{
    auto *bg=reinterpret_cast<const uint16_t*>(background_pixels()),*fg=reinterpret_cast<const uint16_t*>(foreground_pixels());
    const int left=std::clamp(pose.shift-x,0,span),right=std::clamp(width+pose.shift-x,0,span);
    for(int row=y;row<y+8;++row,out+=stride){
      const int pos=row*width+x;
      if(row>=clip_){memcpy(out,fg+pos,2*span);continue;}
      if(left)memcpy(out,bg+pos,2*left);
      if(right<span)memcpy(out+right,bg+pos+right,2*(span-right));
      if(left<right)blend_span(out+left,bg+pos+left,fg+pos+left-pose.shift,right-left,pose.alpha);
    }
  }
  void prepare_patch(int phase,LivePatch &patch)const{
    patch.phase=-1;
    if(!patch.pixels)return;
    const auto &path=nav_paths[route_];
    const auto pose=nav_pose[path.travel==14?0:path.travel==24?1:2][phase];
    const auto album=album_area(pose.shift);
    size_t used=0;
    for(int y=0;y<height;y+=8){
      patch.rows[y/8]=0;
      for(auto tiles=dirty_tiles(y,pose);tiles;tiles&=tiles-1){
        const int x=16*__builtin_ctzll(tiles);
        if(!sd_active_ && inside_album(album,x,y))continue;
        patch.rows[y/8]|=uint64_t(1)<<(x/16);
      }
      for(auto tiles=patch.rows[y/8];tiles;){
        int x;const int span=take_span(tiles,x);
        if(used+8*span>patch.capacity)return;
        paint_span(patch.pixels+used,span,x,y,span,pose);
        used+=8*span;
      }
    }
    patch.phase=phase;
  }
  void overlay(uint16_t *out,int phase,int &first_y,int &end_y)const{
#ifdef STUDY_HOME_ZOOM
    if(home_zoom_){home_zoom_artwork.draw(out,foreground_pixels(),mode_,phase,first_y,end_y);return;}
#endif
    if(!from_variant_ && !to_variant_)return;
    const auto &p=nav_paths[route_];
    const auto pose=nav_pose[p.travel==14?0:p.travel==24?1:2][phase];
    const unsigned a=pose.alpha;
    if(sd_active_ && blend_live_regions(out,pose))return;
    Rect album{};
    const bool complete_patch=sd_active_ && play_patch_->phase==phase;
    const bool album_blended=!complete_patch && blend_album(out,pose.shift,a,album);
    if(play_patch_->phase==phase && (!album.w || album_blended)){
      const uint16_t *pixels=play_patch_->pixels;
      for(int y=0;y<height;y+=8)for(auto tiles=play_patch_->rows[y/8];tiles;){
        int x;const int span=take_span(tiles,x);
        first_y=std::min(first_y,y);end_y=std::max(end_y,y+8);
        for(int row=y;row<y+8;++row,pixels+=span)memcpy(out+row*width+x,pixels,2*span);
      }
      return;
    }
    for(int y=0;y<height;y+=8){
      auto tiles=dirty_tiles(y,pose);
      while(tiles){
        int x;const int span=take_span(tiles,x);
        first_y=std::min(first_y,y);end_y=std::max(end_y,y+8);
        if(album_blended){
          for(int offset=0;offset<span;offset+=16)
            if(!inside_album(album,x+offset,y))paint_span(out+y*width+x+offset,width,x+offset,y,16,pose);
        }else paint_span(out+y*width+x,width,x,y,span,pose);
      }
    }
  }
  bool ids(const Block &b,uint32_t *dest)const{
#ifdef STUDY_PLANAR_MAPS
    // Separate scratch per consumer. Playback assembly and cache preparation
    // can run on different cores.
    auto *planes=reinterpret_cast<uint8_t*>(dest+blocks);
    if(tinfl_decompress_mem_to_mem(planes,blocks*3,maps_+b.offset,b.size,1)!=blocks*3)return false;
    for(int i=0;i<blocks;i++)
      dest[i]=planes[i] | (uint32_t(planes[blocks+i])<<8) | (uint32_t(planes[2*blocks+i])<<16);
    return true;
#else
    return tinfl_decompress_mem_to_mem(dest,blocks*4,maps_+b.offset,b.size,1)==blocks*4;
#endif
  }
  uint8_t *append_raw(uint8_t *ptr,const uint32_t *ids,int begin,int end)const{
    for(int j=begin;j<end;j++){
      auto id=ids[j];
#ifdef STUDY_PACKED_SEGMENTS
      uint32_t offset=offsets_[id/16];
      for(uint32_t n=id&~15u;n<id;n++)offset+=segment_lengths_[n];
      const auto size=segment_lengths_[id];
#else
      auto offset=offsets_[id];auto size=offsets_[id+1]-offset;
#endif
      memcpy(ptr,entropy_+offset,size);ptr+=size;
      *ptr++=0xff;*ptr++=0xd0+(j%8);
    }
    return ptr;
  }
  void free_chunks(){
    heap_caps_free(chunks_);heap_caps_free(chunk_offsets_);chunks_=nullptr;chunk_offsets_=nullptr;
    warm_chunk_=-1;warm_bytes_=0;chunks_ready_=false;
  }
  bool allocate_chunks(){
    if(!prepare_ids_)return false;
    chunks_=static_cast<uint8_t*>(heap_caps_malloc(chunk_bytes,MALLOC_CAP_SPIRAM));
    chunk_offsets_=static_cast<uint32_t*>(heap_caps_malloc((chunk_count+1)*4,MALLOC_CAP_SPIRAM));
    if(!chunks_ || !chunk_offsets_){free_chunks();return false;}
    warm_chunk_=0;warm_bytes_=0;return true;
  }
  void warm_chunks(){
    if(warm_chunk_<0)return;
    const unsigned i=warm_chunk_,n=std::min(128u,chunk_count-i),bytes=n*8*4;
    const auto &recipe=chunk_recipes[i/128];
    if(tinfl_decompress_mem_to_mem(prepare_ids_,bytes,run_data+recipe.offset,recipe.size,1)!=bytes){free_chunks();return;}
    auto *p=chunks_+warm_bytes_;
    for(unsigned j=0;j<n;++j){
      chunk_offsets_[i+j]=p-chunks_;p=append_raw(p,prepare_ids_+8*j,0,8);
    }
    warm_bytes_=p-chunks_;warm_chunk_+=n;
    if(unsigned(warm_chunk_)==chunk_count){
      if(warm_bytes_!=chunk_bytes){free_chunks();return;}
      chunk_offsets_[chunk_count]=chunk_bytes;chunks_ready_=true;warm_chunk_=-1;
    }
  }
  void make_chunks(){
    if(allocate_chunks())while(warm_chunk_>=0){
      warm_chunks();
      esphome::App.feed_wdt();
    }
  }
  bool load_chunks(int route,int phase,uint16_t *out)const{
    if(!chunks_ready_)return false;
    const auto &b=chunk_maps[route*10+phase];
    return tinfl_decompress_mem_to_mem(out,sizeof(play_chunks_),run_data+b.offset,b.size,1)==sizeof(play_chunks_);
  }
  bool assemble(int phase,uint8_t *out){
#ifdef STUDY_HOME_ZOOM
    if(home_zoom_)return home_zoom_artwork.frame(mode_,phase,out,input_size_);
#endif
#ifdef STUDY_SD_NAVIGATION
    if(sd_active_)return navigation_artwork.frame(mode_,route_,phase,out,input_size_);
#endif
    const auto &b=nav_paths[route_].phases[phase];
    if(auto *prepared=cache_[route_].frames[phase]){
      memcpy(out,prepared,b.bytes);return true;
    }
    if(!ids(b,play_ids_))return false;
    auto *groups=load_chunks(route_,phase,play_chunks_)?play_chunks_:nullptr;
    memcpy(out,header_,header_bytes);
    return append(out+header_bytes,play_ids_,groups,0,blocks)==out+b.bytes;
  }
  static void produce(void *arg){
    auto *self=static_cast<Navigation*>(arg);
    for(;;){
      ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
      self->job_ok_=self->assemble(self->queued_,self->next_input_);
      if(self->job_ok_ && !self->sd_active_)self->prepare_patch(self->queued_,*self->next_patch_);
      xSemaphoreGive(self->ready_);
    }
  }
  bool check_colors(){
    if(!scratch)return false;
    size_t size=0;
    auto *pixels=reinterpret_cast<uint16_t*>(scratch);
    jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_RGB565;
    uint32_t written=0;
    cfg.rgb_order=panel_jpeg_order;
    auto shadow_error=[&](){
      int worst=0;
      for(int i=0;i<8;i++){
        const unsigned v=shadow_levels[i];
        const uint16_t reference=((v>>3)<<11)|((v>>2)<<5)|(v>>3);
        worst=std::max(worst,color_error(pixels[320*640+i*80+40],reference));
      }
      return worst;
    };
    size_t legacy_size=0;
    if(mbedtls_base64_decode(input_,input_size_,&legacy_size,reinterpret_cast<const uint8_t*>(legacy_test_frame),sizeof(legacy_test_frame)-1)!=0 ||
       jpeg_decoder_process(decoder(),&cfg,input_,legacy_size,scratch,page_bytes,&written)!=ESP_OK || written!=640*400*2)return false;
    const int legacy_error=shadow_error();
    if(mbedtls_base64_decode(input_,input_size_,&size,reinterpret_cast<const uint8_t*>(test_frame),sizeof(test_frame)-1)!=0)return false;
    for(auto order:{JPEG_DEC_RGB_ELEMENT_ORDER_RGB,panel_jpeg_order}){
      cfg.rgb_order=order;
      if(jpeg_decoder_process(decoder(),&cfg,input_,size,scratch,page_bytes,&written)!=ESP_OK || written!=640*400*2)return false;
      int error=0;
      for(int i=0;i<8;i++)error=std::max(error,color_error(pixels[200*640+i*80+40],test_colors[i]));
      ESP_LOGI("study","RGB565 %s: red=%04x green=%04x blue=%04x; max channel error %d/63",
        order==panel_jpeg_order?"LE":"BE",pixels[200*640+440],pixels[200*640+280],pixels[200*640+520],error);
      if(order==panel_jpeg_order && error>4)return false;
    }
    const int corrected_error=shadow_error();
    ESP_LOGI("study","Shadow ramp: legacy error %d/63, corrected %d/63 (eight levels)",legacy_error,corrected_error);
    if(corrected_error>2)return false;
    route_=probe_route;
    bool ok=assemble(probe_phase,input_);
    route_=-1;
    if(!ok || jpeg_decoder_process(decoder(),&cfg,input_,nav_paths[probe_route].phases[probe_phase].bytes,scratch,page_bytes,&written)!=ESP_OK || written!=page_bytes)return false;
    int worst=0;
    for(const auto &sample:frame_colors)
      worst=std::max(worst,color_error(pixels[sample.y*width+sample.x],sample.pixel));
    ESP_LOGI("study","Home to Lights color check: %u samples, maximum channel error %d/63",unsigned(sizeof(frame_colors)/sizeof(frame_colors[0])),worst);
    return worst<=8;
  }
  void release_job(){
    if(queued_>=0 && !job_done_)xSemaphoreTake(ready_,portMAX_DELAY);
    queued_=-1;job_done_=false;
  }
  void use_sd_memory(){
    if(sd_memory_)return;
    release_job();
    free_chunks();
    heap_caps_free(arena_);arena_=nullptr;arena_size_=used_=0;
    for(auto &cached:cache_)cached=Cached{};
    writing_=nullptr;owner_=-1;
    for(auto &patch:patches_){
      heap_caps_free(patch.pixels);patch.pixels=nullptr;patch.capacity=0;
    }
    sd_memory_=true;
  }
  uint8_t *append(uint8_t *ptr,const uint32_t *ids,const uint16_t *group,int begin,int end)const{
    for(int j=begin;j<end;j+=8){
      unsigned code=group?group[j/8]:0;
      if(!code){ptr=append_raw(ptr,ids,j,j+8);continue;}
      const auto start=chunk_offsets_[code-1],size=chunk_offsets_[code]-start;
      memcpy(ptr,chunks_+start,size);ptr+=size;
    }
    if(end==blocks)ptr[-1]=0xd9;
    return ptr;
  }
  // Home -> Lights is the first movie to warm whenever Home is displayed.
  int warm_index(int i)const{
    if(owner_!=home)return i;
    for(int k=0;k<paths;k++)if(nav_paths[k].from==home && nav_paths[k].to==lights && nav_paths[k].travel==14)
      return i==0?k:i==k?0:i;
    return i;
  }
 public:
#ifdef STUDY_PALETTE_PICKER
  void use_palette_memory(){
    release_job();route_=-1;part_=0;
    free_chunks();
  }
  void restore_chunks(){if(!sd_memory_ && !chunks_ && input_ && prepare_ids_){part_=0;allocate_chunks();}}
#endif
  void begin(){
    for(int page=home;page<=doorbell;++page)
      for(int y=0;y<height;y+=8)
        for(int x=0;x<width;x+=16)
          if(affected(page,x,y,true))overlay_rows_[page][y/8]|=uint64_t(1)<<(x/16);
    const auto *part=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,static_cast<esp_partition_subtype_t>(0x40),"motion");
    const void *base=nullptr;
    if(!part || esp_partition_mmap(part,0,motion_bytes,ESP_PARTITION_MMAP_DATA,&base,&mapping_)!=ESP_OK ||
       memcmp(base,motion_tag,sizeof(motion_tag))!=0){
      ESP_LOGW("study","Study motion pack missing or mismatched");return;
    }
    auto *data=static_cast<const uint8_t*>(base)+sizeof(motion_tag);
#ifdef STUDY_LIVE
    esp_partition_mmap_handle_t tail_mapping;
    const void *tail=nullptr;
    unsigned char digest[32];
    if(esp_partition_mmap(part,tail_offset,tail_size,ESP_PARTITION_MMAP_DATA,&tail,&tail_mapping)!=ESP_OK ||
       mbedtls_sha256(static_cast<const uint8_t*>(tail),tail_size,digest,0) ||
       memcmp(digest,tail_sha,sizeof(digest))){
      ESP_LOGW("study","Motion acceleration table failed verification");return;
    }
    run_data=static_cast<const uint8_t*>(tail);
#endif
    offsets_=reinterpret_cast<const uint32_t*>(data);header_=data+offsets_bytes;
#ifdef STUDY_PACKED_SEGMENTS
    segment_lengths_=data+checkpoint_bytes;
#endif
    entropy_=header_+header_bytes;maps_=entropy_+entropy_bytes;
    jpeg_decode_memory_alloc_cfg_t cfg{};cfg.buffer_direction=JPEG_DEC_ALLOC_INPUT_BUFFER;
    size_t frame_capacity=max_frame;
#ifdef STUDY_SD_NAVIGATION
    static_assert(paths==sd_navigation_routes);
    frame_capacity=std::max(frame_capacity,size_t(sd_navigation_max_frame));
#endif
#ifdef STUDY_HOME_ZOOM
    frame_capacity=std::max(frame_capacity,size_t(home_zoom_max_frame));
#endif
    input_=static_cast<uint8_t*>(jpeg_alloc_decoder_mem(frame_capacity,&cfg,&input_size_));
#ifdef STUDY_PLANAR_MAPS
    constexpr size_t map_buffer_bytes=blocks*7;
#else
    constexpr size_t map_buffer_bytes=blocks*4;
#endif
    prepare_ids_=static_cast<uint32_t*>(heap_caps_malloc(map_buffer_bytes,MALLOC_CAP_SPIRAM));
    play_ids_=static_cast<uint32_t*>(heap_caps_malloc(map_buffer_bytes,MALLOC_CAP_SPIRAM));
    if(!input_ || !play_ids_ || !decoder()){input_=nullptr;ESP_LOGW("study","Navigation decoder unavailable");return;}
    if(!check_colors()){input_=nullptr;ESP_LOGW("study","Native color check failed; using page blend");return;}
    make_chunks();
    if(prepare_ids_)for(size_t size=4*1024*1024;size>=512*1024;size/=2){
      if(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<size+1536*1024)continue;
      arena_=static_cast<uint8_t*>(heap_caps_malloc(size,MALLOC_CAP_SPIRAM));
      if(arena_){arena_size_=size;break;}
    }
    next_input_=static_cast<uint8_t*>(jpeg_alloc_decoder_mem(frame_capacity,&cfg,&input_size_));
    if(next_input_){
      ready_=xSemaphoreCreateBinary();
      if(ready_)xTaskCreatePinnedToCore(produce,"study_motion",24576,this,2,&producer_,xPortGetCoreID()^1);
    }
    remember_tiles();
    if(producer_)for(auto &patch:patches_){
      patch.pixels=static_cast<uint16_t*>(heap_caps_malloc(patch_pixels*2,MALLOC_CAP_SPIRAM));
      if(patch.pixels)patch.capacity=patch_pixels;
    }
    ESP_LOGI("study","Navigation decoder ready: %d routes, %u KiB runs, %u KiB cache, %u KiB free PSRAM",paths,chunks_?chunk_bytes/1024:0,unsigned(arena_size_/1024),unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)/1024));
  }
  void prepare(int page){
#ifdef STUDY_HOME_ZOOM
    home_zoom_artwork.warm();
#endif
#ifdef STUDY_SD_NAVIGATION
    navigation_artwork.warm();
    if(navigation_artwork.ready()){
      use_sd_memory();
      int mode=0;
#ifdef STUDY_PALETTE_PICKER
      mode=palette.selection();
#endif
      warm_fade_background(mode);
      return;
    }
#endif
    if(warm_chunk_>=0){warm_chunks();return;}
    release_job();
    if(!arena_ || !input_ || down || page==doorbell || page==idle)return;
    if(owner_!=page){
      for(auto &c:cache_)c=Cached{};
      owner_=page;used_=0;prepare_route_=prepare_phase_=part_=0;writing_=nullptr;
    }
    while(prepare_route_<paths && nav_paths[warm_index(prepare_route_)].from!=page)++prepare_route_;
    if(prepare_route_==paths)return;
    const int n=warm_index(prepare_route_);auto &b=nav_paths[n].phases[prepare_phase_];
    if(!part_){
      if(used_+b.bytes>arena_size_){prepare_route_=paths;return;}
      if(!ids(b,prepare_ids_)){prepare_route_=paths;return;}
      if(!load_chunks(n,prepare_phase_,prepare_chunks_))memset(prepare_chunks_,0,sizeof(prepare_chunks_));
      writing_=arena_+used_;memcpy(writing_,header_,header_bytes);writing_+=header_bytes;
    }
    const int end=std::min(blocks,part_+960);
    writing_=append(writing_,prepare_ids_,prepare_chunks_,part_,end);part_=end;
    if(part_==blocks){
      cache_[n].frames[prepare_phase_]=arena_+used_;used_+=b.bytes;part_=0;
      if(++prepare_phase_==10){prepare_phase_=0;++prepare_route_;}
    }
  }
  void select(int from,int to,int travel,int64_t tap){
    release_job();
    route_=-1;phase_=-1;first_at_=0;tap_at_=tap;
    play_patch_->phase=next_patch_->phase=-1;
    sd_active_=false;home_zoom_=false;mode_=0;
#ifdef STUDY_PALETTE_PICKER
    mode_=palette.selection();
#endif
#ifdef STUDY_SD_NAVIGATION
    if(navigation_artwork.ready()){
      use_sd_memory();
      sd_active_=true;
      if(reference_mode_!=mode_)remember_tiles(mode_);
    }
#endif
    if(mode_ && !sd_active_)return;
    if(!input_)return;
    for(int i=0;i<paths;i++){
      const auto &p=nav_paths[i];
      if(p.from==from && p.to==to && p.travel==travel){
        route_=i;from_variant_=variant(from);to_variant_=variant(to);clip_=height;
#ifdef STUDY_HOME_ZOOM
        home_zoom_=sd_active_ && to==home && home_zoom_artwork.ready();
#endif
        for(const auto &l:links)if(l.page==to && l.root)clip_=std::min(clip_,l.area.y);
        return;
      }
    }
  }
  bool active()const{return route_>=0;}
  bool theme_fade()const{
#ifdef STUDY_SD_NAVIGATION
    return active() && sd_active_ && sd_navigation_theme_fade;
#else
    return false;
#endif
  }
  void prepare_background(){
#ifdef STUDY_SD_NAVIGATION
    if(theme_fade()){
      // Reuse the palette ground across taps. Low-memory fallback preserves
      // the same fade using the existing buffer instead of failing navigation.
      if(!warm_fade_background(mode_)){
        const uint32_t pixel=sd_navigation_backgrounds[mode_];
        std::fill_n(reinterpret_cast<uint32_t*>(previous_pixels),page_bytes/4,pixel|(pixel<<16));
      }
      from_variant_=false;
    }
#endif
  }
  void prefetch(){
    if(sd_active_ && active() && producer_ && queued_<0){
      queued_=0;job_done_=false;xTaskNotifyGive(producer_);
    }
  }
  void cancel(){release_job();route_=-1;}
  void prepare_live_tiles(){
    if(!active())return;
#ifdef STUDY_HOME_ZOOM
    if(home_zoom_){home_zoom_artwork.prepare(mode_,thermostat.temperature,player().playing);return;}
#endif
    const auto &p=nav_paths[route_];
    if(from_variant_)find_changes(p.from,previous_pixels,changed_rows_[0]);
    if(to_variant_)find_changes(p.to,foreground_pixels(),changed_rows_[1]);
  }
  bool can_prepare_endpoint()const{return active() && !from_variant_ && !to_variant_;}
  bool draw(int elapsed){
    int phase=std::min(10,(elapsed+9)/18);
    // The ninth pose already has zero displacement and full opacity. Present
    // the lossless endpoint there so the final framebuffer copy lands on time.
    if(phase==9)phase=10;
    if(phase<=phase_)return false;
    if(queued_>=0 && phase<10){
      if(!job_done_)job_done_=xSemaphoreTake(ready_,0)==pdTRUE;
      if(!job_done_)return false;
      if(!job_ok_){release_job();route_=-1;return false;}
      phase=queued_;
    }
    auto *slot=scanout.acquire(false,true);
    if(!slot)return false;
    const auto &p=nav_paths[route_];
    int first_y=height,end_y=0;
    if(phase==10){release_job();await_page();scanout.copy_pixels(slot->pixels,foreground_pixels(),page_bytes);first_y=0;end_y=height;}
    else{
      const auto &b=p.phases[phase];
      size_t frame_bytes=b.bytes;
#ifdef STUDY_SD_NAVIGATION
      if(sd_active_)frame_bytes=navigation_artwork.frame_size(mode_,route_,phase);
#endif
#ifdef STUDY_HOME_ZOOM
      if(home_zoom_)frame_bytes=home_zoom_artwork.frame_size(mode_,phase);
#endif
      if(queued_>=0){
        std::swap(input_,next_input_);std::swap(play_patch_,next_patch_);queued_=-1;job_done_=false;
      }else if(!assemble(phase,input_)){route_=-1;return false;}
      if(producer_ && phase<8){
        // A late producer may skip a phase to stay within the theme duration.
        queued_=std::min(8,std::max(phase+1,elapsed/18+1));xTaskNotifyGive(producer_);
      }
      jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_RGB565;cfg.rgb_order=panel_jpeg_order;
      uint32_t written=0;
      if(jpeg_decoder_process(decoder(),&cfg,input_,frame_bytes,slot->pixels,page_bytes,&written)!=ESP_OK || written!=page_bytes){
        ESP_LOGW("study","Navigation decode failed");release_job();route_=-1;return false;
      }
      overlay(reinterpret_cast<uint16_t*>(slot->pixels),phase,first_y,end_y);
    }
    slot->lamp_background=false;
    // The decoder wrote directly to the scanout frame. Only CPU-painted
    // rows need a writeback before selecting it at the refresh boundary.
    if(end_y==0){first_y=0;end_y=1;}
    if(!scanout.present(slot,first_y,end_y))return false;
    slot->page=phase==10?revision:0;phase_=phase;++motion_frames;
    if(!first_at_)first_at_=clock_ms();
    if(phase!=10)return false;
    ESP_LOGI("study","Navigation %s > %s (%d): %d frames in %lld ms; first %lld ms from request",
             page_names[p.from],page_names[p.to],p.travel,motion_frames,clock_ms()-motion_start,first_at_-tap_at_);
    route_=-1;return true;
  }
};
static Navigation nav;
}
