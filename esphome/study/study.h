#pragma once
#include "study_assets.h"
#if __has_include("live_runtime/study_profile.h")
#define STUDY_LIVE
#include "live_runtime/study_profile.h"
#endif
#include "scanout.h"
#include "esphome/components/display/display.h"
#include "driver/jpeg_decode.h"
#include "driver/ppa.h"
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"
#include <algorithm>
#include <esp_timer.h>

// P4 ROM ABI; input is a zlib-wrapped, firmware-embedded RGB565 sprite.
extern "C" size_t tinfl_decompress_mem_to_mem(void *, size_t, const void *, size_t, int);
namespace study {
using esphome::display::Display;
static Display *lcd;
static uint8_t *scratch;
static int current=home, history[24], depth=0;
static int levels[light_count];
static bool down=false,dragging=false;
static int pressed=-2;
static int scene=-1, x0,y0,dx,dy;
static int64_t touched_at;
static unsigned slider_updates, slider_draw_us;
static bool root_link=false;
static uint32_t deadline;
static int64_t clock_ms() {return esp_timer_get_time()/1000;}
constexpr int width=720, height=1280, page_bytes=width*height*2;
static uint8_t *room_pixels, *page_pixels, *previous_pixels, *mixed_pixels, *lights_pixels, *lamp_pixels;
static Scanout scanout;
static uint32_t revision=1;
static bool blit(int x,int y,int w,int h,uint8_t *pixels,int stride=0) {
  if(!lcd)return true;
  if(!scanout.active){
    lcd->draw_pixels_at(x,y,w,h,pixels,esphome::display::COLOR_ORDER_RGB,
                      esphome::display::COLOR_BITNESS_565,false,0,0,stride?stride-w:0);
    return true;
  }
  auto *slot=scanout.acquire(true);
  if(!slot)return false;
  const bool full=w==width && h==height;
  const bool seed=!full && slot->page!=revision;
  if(seed)memcpy(slot->pixels,page_pixels,page_bytes);
  if(full)memcpy(slot->pixels,pixels,page_bytes);
  else if(!seed || !stride) {
    for(int row=0;row<h;row++)
      memcpy(slot->pixels+2*((y+row)*width+x),pixels+2*row*(stride?stride:w),2*w);
  }
  slot->page=revision;
  slot->lamp_background=current==lights || current==light0;
  return scanout.present(slot,seed?0:y,seed?height:y+h);
}
static ppa_client_handle_t blender;
static int64_t motion_start;
static int travel, motion_frames, motion_height;
static bool moving;
static void await_page();
}
#include "navigation.h"
namespace study {
static uint8_t *page_buffer() {
  return static_cast<uint8_t*>(heap_caps_aligned_alloc(128,page_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
}
static bool unpack(const Sprite &s,uint8_t *out) {
  const size_t size=size_t(s.w)*s.h*2;
  return out && tinfl_decompress_mem_to_mem(out,size,artwork+s.offset,s.size,1)==size;
}
// The foreground can present prepared JPEGs while the other core restores
// the exact native endpoint. Buffer ownership returns before touch, a new
// navigation request, a fallback blend or the final presentation.
static TaskHandle_t page_worker;
static SemaphoreHandle_t page_done;
static const Sprite *worker_art;
static const uint8_t *worker_source;
static uint8_t *worker_target;
static bool page_pending;
static void decode_page_task(void *){
  for(;;){
    ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    if(worker_source)memcpy(worker_target,worker_source,page_bytes);
    else unpack(*worker_art,worker_target);
    xSemaphoreGive(page_done);
  }
}
static void await_page(){
  if(page_pending){
    xSemaphoreTake(page_done,portMAX_DELAY);page_pending=false;
  }
}
// Only the differing native RGB565 spans need a timeline. Everything outside
// them is identical on Lights and Mushroom Lamp, even when brightness changes.
constexpr int lamp_steps=11;
static uint16_t *timeline;
static int prepared_level=-2,build_step=2*lamp_steps,build_span;
static unsigned build_offset;
static int playback_direction=-1,last_phase=-1;
static bool bench_demo;
static bool navigation_demo;
static uint32_t demo_at;
static int demo_step;

static float ease_out(float t) {
  float lo=0,hi=1;
  for(int n=0;n<8;n++){
    const float u=(lo+hi)*.5f;
    if(u*u*(1.74f-.74f*u)<t)lo=u;else hi=u;
  }
  const float u=(lo+hi)*.5f;
  return u*u*(3.f-2.f*u);
}
static void prepare_lamp() {
  if(!timeline || !lamp_pixels || !lights_pixels || !scratch || down || current==doorbell)return;
  if(prepared_level!=levels[0]){
    prepared_level=levels[0];build_step=0;build_span=0;build_offset=0;
    if(prepared_level>=0)for(int i=0;i<2;i++){
      auto &r=i?slider:reading;
      auto &s=patches[prepared_level][i];
      if(unpack(s,scratch))for(int y=0;y<s.h;y++)
        memcpy(lamp_pixels+2*((r.y+y)*width+r.x),scratch+2*y*s.w,2*s.w);
    }
  }
  if(build_step>=2*lamp_steps)return;
  const int dir=build_step/lamp_steps,phase=build_step%lamp_steps;
  const float e=ease_out(float(phase)/(lamp_steps-1));
  const int shift=phase==lamp_steps-1?0:std::lround(14*(1-e));
  const unsigned a=phase==lamp_steps-1?32:std::lround(32*(.3f+.7f*e)),b=32-a;
  auto *bg=reinterpret_cast<uint16_t*>(dir?lamp_pixels:lights_pixels);
  auto *fg=reinterpret_cast<uint16_t*>(dir?lights_pixels:lamp_pixels);
  const auto *gutter=reinterpret_cast<const uint16_t*>(lights_pixels);
  auto *dst=timeline+build_step*lamp_stride;
  const auto stop=esp_timer_get_time()+1500;
  do {
    const auto &r=lamp_spans[build_span++];
    const int row=r.y*width;
    for(int x=r.x;x<r.x+r.w;x++){
      const unsigned p=bg[row+x],q=fg[row+std::max(0,x-shift)];
      unsigned value=p;
      if(r.y>=lamp_clip[dir])value=fg[row+x];
      else if(x>=shift && (p!=gutter[row+(x%4)] || q!=gutter[row+((x-shift)%4)])){
        value=((((p&0xf81f)*b+(q&0xf81f)*a)>>5)&0xf81f) |
              ((((p&0x07e0)*b+(q&0x07e0)*a)>>5)&0x07e0);
      }
      dst[build_offset++]=value;
    }
    if(build_span==sizeof(lamp_spans)/sizeof(lamp_spans[0])){
      build_span=0;build_offset=0;++build_step;
      if(build_step==2*lamp_steps)ESP_LOGI("study","Lamp transition frames ready for level %d",prepared_level);
      break;
    }
  }while(esp_timer_get_time()<stop);
}
static void animate_cached(int elapsed) {
  const int phase=std::min(lamp_steps-1,(elapsed+9)/18);
  if(phase==last_phase)return;
  auto *slot=scanout.acquire(false);
  if(!slot)return;
  const bool seed=!slot->lamp_background;
  if(seed)memcpy(slot->pixels,lights_pixels,page_bytes);
  auto *src=timeline+(playback_direction*lamp_steps+phase)*lamp_stride;
  for(const auto &r:lamp_spans){
    memcpy(slot->pixels+2*(r.y*width+r.x),src,2*r.w);
    src+=r.w;
  }
  const auto &first=lamp_spans[0],&last=lamp_spans[sizeof(lamp_spans)/sizeof(lamp_spans[0])-1];
  if(!scanout.present(slot,seed?0:first.y,seed?height:last.y+1))return;
  slot->lamp_background=true;last_phase=phase;++motion_frames;
  slot->page=phase==lamp_steps-1?revision:0;
  if(phase==lamp_steps-1){
    moving=false;
    ESP_LOGI("study","Cached lamp transition: %d frames in %lld ms",motion_frames,clock_ms()-motion_start);
  }
}
static void draw_patch(const Sprite &s,const Rect &area,bool update_display) {
  if(!unpack(s,scratch))return;
  if(page_pixels)for(int row=0;row<s.h;row++)
    memcpy(page_pixels+2*((area.y+row)*width+area.x),scratch+2*row*s.w,2*s.w);
  if(update_display)blit(area.x,area.y,s.w,s.h,scratch);
}
static int light_index() {
  int i=current-light0;
  return i>=0 && i<light_count?i:-1;
}
static void paint_level(int value,bool update_display=true) {
#ifdef STUDY_LIVE
  if(value<0){
    if(!page_pixels)return;
    // Hide the photographed value and thumb until HA confirms this entity.
    auto *pixels=reinterpret_cast<uint16_t*>(page_pixels);
    for(auto area:{reading,slider}){
      for(int row=area.y;row<area.y+area.h;row++){
        auto *line=pixels+row*width;
        std::fill_n(line+area.x,area.w,line[area.x-1]);
        if(area.y==reading.y && std::abs(row-area.y-area.h/2)<3)
          std::fill_n(line+area.x+area.w/2-15,30,uint16_t(0x7bef));
      }
      if(update_display)blit(area.x,area.y,area.w,area.h,page_pixels+2*(area.y*width+area.x),width);
    }
    return;
  }
#endif
  if(scanout.active){
    draw_patch(patches[value][0],reading,false);
    draw_patch(patches[value][1],slider,false);
    if(update_display){
      const int x=std::min(reading.x,slider.x),y=std::min(reading.y,slider.y);
      const int w=std::max(reading.x+reading.w,slider.x+slider.w)-x;
      const int h=std::max(reading.y+reading.h,slider.y+slider.h)-y;
      blit(x,y,w,h,page_pixels+2*(y*width+x),width);
    }
    return;
  }
  draw_patch(patches[value][0],reading,update_display);
  draw_patch(patches[value][1],slider,update_display);
}
static void animate() {
  if(!moving){prepare_lamp();nav.prepare(current);return;}
  const int elapsed=clock_ms()-motion_start;
  if(playback_direction>=0){animate_cached(elapsed);return;}
  if(nav.active()){if(nav.draw(elapsed))moving=false;return;}
  await_page();
  if(elapsed>=180) {
    blit(0,0,width,height,page_pixels);
    moving=false;
    ESP_LOGI("study","Page transition: %d frames in %lld ms",motion_frames+1,clock_ms()-motion_start);
    return;
  }
  // CSS ease-out is cubic-bezier(0,0,.58,1). Invert its time component.
  const float ease=ease_out(elapsed/180.f);
  const int offset=std::lround(travel*(1.f-ease));
  const unsigned dest_x=std::max(offset,0),src_x=std::max(-offset,0);
  auto *slot=scanout.active?scanout.acquire(false):nullptr;
  if(scanout.active && !slot)return;
  uint8_t *out=slot?slot->pixels:mixed_pixels;
  if(slot){
    const int edge=std::abs(offset),x=offset<0?width-edge:0;
    if(edge)for(int y=0;y<motion_height;y++){
      const int pos=2*(y*width+x);
      memcpy(out+pos,previous_pixels+pos,2*edge);
    }
    memcpy(out+2*width*motion_height,page_pixels+2*width*motion_height,2*width*(height-motion_height));
    slot->page=0;
    slot->lamp_background=false;
  }
  ppa_blend_oper_config_t op{};
  op.in_bg.buffer=previous_pixels;
  op.in_bg.pic_w=width; op.in_bg.pic_h=height;
  op.in_bg.block_w=width-std::abs(offset); op.in_bg.block_h=motion_height;
  op.in_bg.block_offset_x=dest_x; op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
  op.in_fg=op.in_bg; op.in_fg.buffer=page_pixels; op.in_fg.block_offset_x=src_x;
  op.out.buffer=out; op.out.buffer_size=page_bytes;
  op.out.pic_w=width; op.out.pic_h=height; op.out.block_offset_x=dest_x;
  op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
  op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE; op.bg_alpha_fix_val=255;
  const float initial_alpha=std::abs(travel)==24?.35f:.30f;
  op.fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;
  op.fg_alpha_fix_val=std::lround(255*(initial_alpha+(1.f-initial_alpha)*ease));
  if(ppa_do_blend(blender,&op)!=ESP_OK){
    moving=false;blit(0,0,width,height,page_pixels);return;
  }
  if(slot){if(!scanout.present(slot,0,height))return;}
  else blit(0,0,width,motion_height,mixed_pixels);
  ++motion_frames;
}
static void show(int dest,int shift=14) {
  const auto request_at=clock_ms();
  await_page();
  const bool change=dest!=current;
  playback_direction=-1;last_phase=-1;
  if(timeline && build_step==2*lamp_steps && levels[0]==prepared_level && shift==14){
    if(current==lights && dest==light0)playback_direction=0;
    if(current==light0 && dest==lights)playback_direction=1;
  }
  nav.select(current,dest,shift,request_at);
  const bool transition=change && shift && blender && current!=idle && current!=doorbell && dest!=idle && dest!=doorbell && (dest!=home || nav.active());
  if(transition)std::swap(previous_pixels,page_pixels);
  moving=false;
  current=dest;
  ++revision;
  auto &art=current==scenes && scene>=0?scene_sprites[scene]:pages[current];
  auto *target=page_pixels?page_pixels:scratch;
  if(!target)return;
  const auto *cached=dest==home?room_pixels:dest==lights?lights_pixels:dest==light0?lamp_pixels:nullptr;
  int i=light_index();
  const bool parallel=transition && page_worker && playback_direction<0 && nav.can_prepare_endpoint()
#ifdef STUDY_LIVE
      && i<0
#endif
      ;
  if(parallel){
    worker_art=&art;worker_target=target;
    worker_source=dest==light0 && prepared_level!=levels[0]?nullptr:cached;
    page_pending=true;xTaskNotifyGive(page_worker);
  }else{
    if(cached)memcpy(target,cached,page_bytes);
    else if(!unpack(art,target))return;
    if(page_pixels && i>=0)paint_level(levels[i],false);
  }
  if(transition) {
    motion_height=height;
    for(const auto &link:links)if(link.page==dest && link.root)
      motion_height=std::min(motion_height,link.area.y);
    if(!scanout.active && motion_height<height)
      blit(0,motion_height,width,height-motion_height,target+2*width*motion_height);
    if(!scanout.active)memcpy(mixed_pixels,previous_pixels,page_bytes);
    travel=shift;motion_frames=0;motion_start=clock_ms();moving=true;
    animate();
  } else {
    blit(0,0,width,height,target);
    if(!page_pixels && i>=0 && levels[i]>=0)paint_level(levels[i]);
  }
}
static void go(int dest) {
  if(dest<=-6 && dest>=-8) {
    scene=-6-dest;
#ifdef STUDY_LIVE
    const auto &profile=fleet.active();
    for(int i=0;i<light_count;i++)if(profile.members[i])
      ha_lights.request(i,scene==0?profile.soft[i]:scene==2?profile.bright[i]:0);
#else
    for(int i=0;i<light_count;i++)if(presets[scene][i]>=0)levels[i]=presets[scene][i];
#endif
    show(current);return;
  }
  if(dest<=-3 && dest>=-5) {
    int i=light_index();if(i<0)return;
#ifdef STUDY_LIVE
    int actual=ha_lights.confirmed(i);
    if(actual<0)return;
    int restore=last_on[i]?last_on[i]:std::max(1,fleet.active().bright[i]);
    ha_lights.request(i,dest==-5?(actual?0:restore):std::clamp(actual+(dest==-3?5:-5),0,100));
    return;
#else
    int v=dest==-5?(levels[i]?0:100):levels[i]+(dest==-3?5:-5);
    levels[i]=std::clamp(v,0,100);scene=-1;paint_level(levels[i]);return;
#endif
  }
  if(dest==-1) {show(depth?history[--depth]:home);return;}
  if(dest==current)return;
  if(depth==24) depth=0;
  history[depth++]=current;
  show(dest);
}
static void begin(Display *display) {
  lcd=display;
  scratch=page_buffer();
  if(lcd) {
    room_pixels=page_buffer();
    if(!unpack(pages[home],room_pixels)){heap_caps_free(room_pixels);room_pixels=nullptr;}
    page_pixels=page_buffer();previous_pixels=page_buffer();
    if(page_pixels && scanout.begin(static_cast<Scanout::Panel*>(lcd))){
      ESP_LOGI("study","Three refresh-paced DSI buffers ready");
    } else mixed_pixels=page_buffer();
    ppa_client_config_t config{};config.oper_type=PPA_OPERATION_BLEND;
    if(previous_pixels && page_pixels && (scanout.active || mixed_pixels))ppa_register_client(&config,&blender);
  }
#ifdef STUDY_LIVE
  std::fill_n(levels,light_count,-1);
  room_start();
#else
  std::copy_n(initial,light_count,levels);
#endif
  const int64_t start=clock_ms();
  show(home);
  ESP_LOGI("study","Study home unpacked in %lld ms; display %s",clock_ms()-start,lcd?"attached":"absent");
  if(lcd){
    esphome::App.set_loop_interval(8);
    lights_pixels=page_buffer();lamp_pixels=page_buffer();
    if(!unpack(pages[lights],lights_pixels)){heap_caps_free(lights_pixels);lights_pixels=nullptr;}
    if(!unpack(pages[light0],lamp_pixels)){heap_caps_free(lamp_pixels);lamp_pixels=nullptr;}
    if(scanout.active && lamp_pixels && lights_pixels && previous_pixels && blender){
      timeline=static_cast<uint16_t*>(heap_caps_malloc(2*lamp_steps*lamp_stride*sizeof(uint16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      ESP_LOGI("study","Lamp frame cache %s",timeline?"allocated":"unavailable");
    }
    ESP_LOGI("study","Study page animation %s",blender?"ready":"unavailable");
    if(scanout.active && blender)nav.begin();
    if(scanout.active && blender){
      page_done=xSemaphoreCreateBinary();
      if(page_done)xTaskCreatePinnedToCore(decode_page_task,"study_page",24576,nullptr,1,&page_worker,xPortGetCoreID()^1);
    }
  }
}
static void touch(int x,int y) {
  bench_demo=false;
  const int i=light_index();
  if(!down) {
    if(moving){await_page();moving=false;blit(0,0,width,height,page_pixels);}
    down=true;pressed=-2;dragging=i>=0 && slider.contains(x,y);
#ifdef STUDY_LIVE
    dragging=dragging && ha_lights.confirmed(i)>=0;
#endif
    if(dragging){slider_updates=0;slider_draw_us=0;}
    x0=x;y0=y;dx=dy=0;root_link=false;touched_at=clock_ms();
    if(current==idle)pressed=-1;
    else for(const auto &link:links)
      if(link.page==current && link.area.contains(x,y)){pressed=link.dest;root_link=link.root;break;}
  }
  dx=x-x0;dy=y-y0;
  if(dragging && i>=0) {
    int value=std::clamp((x-slider.x)*100/slider.w,0,100);
    if(value!=levels[i]){
      const auto start=esp_timer_get_time();
      levels[i]=value;scene=-1;paint_level(value);
      slider_draw_us+=esp_timer_get_time()-start;++slider_updates;
    }
  } else if(pressed!=-2 && current!=idle) {
    bool inside=false;
    for(const auto &link:links)
      if(link.page==current && link.dest==pressed && link.area.contains(x,y))inside=true;
    if(!inside)pressed=-2;
  }
}
static void release() {
#ifdef STUDY_LIVE
  if(dragging && slider_updates){
    const auto index=light_index();
    if(index>=0){ha_lights.request(index,levels[index]);live_dirty[index]=true;}
  }
#endif
  if(dragging && slider_updates)
    ESP_LOGI("study","Slider: %u changes over %lld ms; mean redraw %u us",slider_updates,clock_ms()-touched_at,slider_draw_us/slider_updates);
  if(down && !dragging) {
    if(current<=media && !root_link && std::abs(dx)>=90 && std::abs(dx)*2>=std::abs(dy)*3 && clock_ms()-touched_at<=1200) {
      int dest=current+(dx<0?1:-1);
      if(dest>=home && dest<=media){depth=0;if(dest!=home)history[depth++]=home;show(dest,dx<0?24:-24);}
    } else if(pressed!=-2) {
      if(root_link){
        depth=0;if(pressed!=home)history[depth++]=home;
        if(pressed!=current)show(pressed);
      }else go(pressed);
    }
  }
  down=false;dragging=false;pressed=-2;
}
static void ring() {
  bench_demo=false;
  down=false;dragging=false;pressed=-2;
  if(current!=doorbell)go(doorbell);
  deadline=clock_ms()+60000;
}
static void close_ring() {if(current==doorbell)go(-1);}
static bool start_demo() {
  if(current!=home || down || moving || !timeline || build_step!=2*lamp_steps || prepared_level!=levels[0])return false;
  bench_demo=true;navigation_demo=false;demo_step=0;demo_at=clock_ms();
  return true;
}
static bool start_navigation_demo(){
  if(current!=home || down || moving || bench_demo)return false;
  navigation_demo=bench_demo=true;demo_step=0;demo_at=clock_ms();return true;
}
static void tick() {
#ifdef STUDY_LIVE
  ha_lights.tick();
  fleet.tick(ha_lights.receiving());
  if(!moving && !down){
    for(int i=0;i<light_count;i++)if(live_dirty[i]){
      live_dirty[i]=false;
      levels[i]=ha_lights.confirmed(i);
      if(i==light_index())paint_level(levels[i]);
    }
  }
#endif
  if(bench_demo && !moving && int32_t(uint32_t(clock_ms())-demo_at)>=0){
    if(navigation_demo){
      if(demo_step==2*sizeof(nav_paths)/sizeof(nav_paths[0])){
        depth=0;show(home,0);bench_demo=navigation_demo=false;
        ESP_LOGI("study","Navigation replay complete");
      }else{
        const auto &path=nav_paths[demo_step/2];
        if(demo_step%2==0)show(path.from,0);else show(path.to,path.travel);
        ++demo_step;
      }
      demo_at=clock_ms()+250;
    }else{
    if(demo_step==0)go(lights);
    else if(demo_step==1 || demo_step==3)go(light0);
    else go(-1);
    if(++demo_step==6)bench_demo=false;
    demo_at=clock_ms()+650;
    }
  }
  static int64_t since;
  static uint32_t refresh_begin;
  static bool measured;
  if(scanout.active && !measured){
    const auto now=clock_ms();
    if(!since){since=now;refresh_begin=Scanout::Panel::refresh_epoch;}
    else if(now-since>=1000){
      ESP_LOGI("study","DSI refresh: %u cycles over %lld ms",unsigned(Scanout::Panel::refresh_epoch-refresh_begin),now-since);
      measured=true;
    }
  }
  if(current==doorbell && int32_t(uint32_t(clock_ms())-deadline)>=0)close_ring();
}
static bool frame(const std::string &encoded) {
  if(!scratch || current!=doorbell || encoded.empty() || encoded.size()>60000)return false;
  auto engine=decoder();
  static uint8_t *input, *output;
  static size_t in_size,out_size;
  if(!engine)return false;
  if(!input) {
    jpeg_decode_memory_alloc_cfg_t cfg{};cfg.buffer_direction=JPEG_DEC_ALLOC_INPUT_BUFFER;
    input=(uint8_t*)jpeg_alloc_decoder_mem(45000,&cfg,&in_size);
  }
  if(!output) {
    jpeg_decode_memory_alloc_cfg_t cfg{};cfg.buffer_direction=JPEG_DEC_ALLOC_OUTPUT_BUFFER;
    output=(uint8_t*)jpeg_alloc_decoder_mem(640*400*2,&cfg,&out_size);
  }
  size_t bytes=0;
  if(!input || !output || mbedtls_base64_decode(input,in_size,&bytes,
    reinterpret_cast<const unsigned char*>(encoded.data()),encoded.size())!=0)return false;
  jpeg_decode_picture_info_t info{};
  if(jpeg_decoder_get_info(input,bytes,&info)!=ESP_OK || info.width!=640 || info.height!=400)return false;
  jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_RGB565;
  cfg.rgb_order=panel_jpeg_order;
  uint32_t written=0;
  if(jpeg_decoder_process(engine,&cfg,input,bytes,output,out_size,&written)!=ESP_OK || written!=640*400*2)return false;
  return blit(40,video_y,640,400,output);
}
static void headless_test() {
  if(lcd || !scratch)return;
  ring();
  int64_t start=clock_ms();
  unsigned count=0;
  for(unsigned i=0;i<20 && frame(test_frame);++i)++count;
  ESP_LOGI("study","Headless JPEG test: %u/20 local colour bars decoded in %lld ms; no scanout",count,clock_ms()-start);
  close_ring();
}
}
