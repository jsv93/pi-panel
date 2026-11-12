#pragma once
#include "study_assets.h"
#if __has_include("live_runtime/study_profile.h")
#define STUDY_LIVE
#include "control_art.h"
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
#ifdef STUDY_LIVE
static int (*minutes_now)();
static bool (*set_light_level)(int);
static void screen_callbacks(int (*clock)(),bool (*brightness)(int)){
  minutes_now=clock;set_light_level=brightness;
}
static int64_t last_activity,dim_since;
static int wake_page=home,shown_minute=-2,applied_brightness=-1;
static bool blanked=false,wake_touch=false;
static double brightness_target=backlight_default,brightness_now=backlight_default;
static int manual_brightness=backlight_default,shown_brightness=-1,preview_brightness=-1;
static int64_t override_until=0;
static int screen_level(){
  if(lux_entity[0] && clock_ms()>=override_until)
    return std::clamp(int(std::lround(brightness_now)),1,100);
  return manual_brightness;
}
static void apply_brightness(){
  const int normal=screen_level();
  const int value=blanked?0:current==idle?std::max(lux_entity[0]?1:10,int(std::lround(normal*.25))):normal;
  if(value!=applied_brightness && set_light_level && set_light_level(value)){
    applied_brightness=value;
    ESP_LOGD("study","Backlight %d%%",value);
  }
}
#endif
constexpr int width=720, height=1280, page_bytes=width*height*2;
static uint8_t *room_pixels, *page_pixels, *previous_pixels, *mixed_pixels, *lights_pixels, *lamp_pixels;
#ifdef STUDY_LIVE
static void control_patch(uint8_t *target,const Sprite &s,const Rect &area);
#endif
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
#ifdef STUDY_LIVE
    control_patch(lamp_pixels,detail_modes[prepared_level<0?0:prepared_level==0?1:2],detail_power_button);
#endif
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
  if(phase==lamp_steps-1){
    memcpy(slot->pixels,page_pixels,page_bytes);
    if(!scanout.present(slot,0,height))return;
    slot->lamp_background=false;slot->page=revision;moving=false;++motion_frames;
    ESP_LOGI("study","Cached lamp transition: %d frames in %lld ms",motion_frames,clock_ms()-motion_start);
    return;
  }
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
  slot->page=0;
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
#ifdef STUDY_LIVE
static void control_patch(uint8_t *target,const Sprite &s,const Rect &area){
  if(!target || !scratch)return;
  const size_t bytes=2*s.w*s.h;
  if(tinfl_decompress_mem_to_mem(scratch,bytes,control_art+s.offset,s.size,1)!=bytes)return;
  for(int y=0;y<s.h;y++)
    memcpy(target+2*((area.y+y)*width+area.x),scratch+2*y*s.w,2*s.w);
}
static void display_field(int level){
  shown_brightness=level;
  control_patch(page_pixels,backlight_modes[level][0],backlight_rail);
  control_patch(page_pixels,backlight_modes[level][1],backlight_value);
}
static void transport_fields(){
  control_patch(page_pixels,shuffle_modes[player.shuffled],transport_buttons[0]);
  control_patch(page_pixels,play_modes[player.playing],transport_buttons[2]);
  control_patch(page_pixels,repeat_modes[player.repeat_mode],transport_buttons[4]);
}
static int transport_hit(int x,int y){
  if(current==media)for(int i=0;i<5;i++)if(transport_buttons[i].contains(x,y))return -120-i;
  return -2;
}
static void number_field(int field,float value,int decimals,unsigned opacity=255){
  const auto &r=number_rects[field];
  control_patch(page_pixels,number_backgrounds[field],r);
  char text[24];
  if(std::isfinite(value))snprintf(text,sizeof(text),"%.*f",decimals,double(value));
  else strcpy(text,"~");
  int pen=0;
  const auto colour=number_colours[field];
  for(size_t i=0;i<=strlen(text);i++){
    const char c=text[i];
    int index=c==0?13:c=='~'?12:c=='-'?11:c=='.'?10:c-'0';
    if(index<0 || index>=14)continue;
    const auto &g=number_glyphs[field][index];
    if(g.size && tinfl_decompress_mem_to_mem(scratch,g.w*g.h,control_art+g.pos,g.size,1)==size_t(g.w*g.h)){
      for(int row=0;row<g.h;row++)for(int col=0;col<g.w;col++){
        const int x=(pen+32)/64+g.x+col,y=g.y+row;
        unsigned a=(scratch[row*g.w+col]*opacity+127)/255;
        if(!a || x<0 || x>=r.w || y<0 || y>=r.h)continue;
        auto &px=reinterpret_cast<uint16_t*>(page_pixels)[(r.y+y)*width+r.x+x];
        const unsigned b=255-a;
        px=(((((px>>11)*b+(colour>>11)*a+127)/255)<<11) |
            (((((px>>5)&63)*b+((colour>>5)&63)*a+127)/255)<<5) |
            (((px&31)*b+(colour&31)*a+127)/255));
      }
    }
    pen+=g.advance;
  }
}
static bool climate_drag=false;
static float climate_preview=NAN;
static int edit_slot=-1,edit_feedback=0,edit_count=0;
static bool edit_waiting=false;
static int64_t feedback_until=0;
static int edit_hit(int x,int y){
  if(current==edit_page)for(int i=0;i<2;i++)if(save_buttons[i].contains(x,y))return -100-i;
  if(current==members_page)for(int i=0;i<light_count;i++)if(member_buttons[i].contains(x,y))return -102-i;
  return -2;
}
static void edit_fields(){
  if(current==edit_page)for(int i=0;i<2;i++)
    control_patch(page_pixels,save_feedback[edit_slot==i?edit_feedback:0][i],save_messages[i]);
  if(current==members_page)for(int i=0;i<light_count;i++){
    bool included=fleet.active().members[i];
    if(edit_waiting && edit_slot==i+2)included=!included;
    const int mode=int(included)+(edit_slot==i+2 && edit_feedback==2?2:0);
    control_patch(page_pixels,membership_modes[mode][i],member_status[i]);
  }
}
static void refresh_edit(){
  if(!moving && page_pixels && (current==edit_page || current==members_page)){
    edit_fields();++revision;blit(0,0,width,height,page_pixels);
  }
}
static void edit_scene(int slot){
  if(edit_waiting)return;
  using Edit=decltype(fleet)::Edit;
  const bool preset=slot<2;
  std::string body;
  edit_slot=slot;edit_count=0;
  if(preset){
    body=slot==0?"{\"preset\":\"soft\",\"levels\":{":"{\"preset\":\"bright\",\"levels\":{";
    for(int i=0;i<light_count;i++){
      if(!fleet.active().members[i])continue;
      const int v=ha_lights.confirmed(i);
      if(v<0){edit_feedback=2;feedback_until=clock_ms()+4000;refresh_edit();return;}
      if(edit_count++)body+=",";
      body+="\""+std::string(room_entities[i])+"\":"+std::to_string(v);
    }
    body+="}}";
  }else{
    const int i=slot-2;
    body="{\"entity_id\":\""+std::string(room_entities[i])+"\",\"include_presets\":"+
         (fleet.active().members[i]?"false}":"true}");
  }
  const bool empty=preset && !edit_count;
  edit_waiting=!empty && fleet.submit(preset?Edit::preset:Edit::membership,body);
  edit_feedback=edit_waiting?1:empty?3:2;
  feedback_until=clock_ms()+4000;
  refresh_edit();
}
static void climate_field(){
  if(!page_pixels)return;
  if(current==home)number_field(0,thermostat.temperature,1);
  if(current!=climate_page)return;
  number_field(1,thermostat.temperature,1);
  number_field(2,thermostat.humidity,0);
  const float target=climate_drag?climate_preview:thermostat.target;
  const bool valid=thermostat.can_adjust();
  const bool active=valid && thermostat.running;
  number_field(3,valid?std::round(target*2)/2:NAN,1,active?255:115);
  const int percent=valid?std::clamp(int(std::lround(100*(target-thermostat.minimum)/
                                               (thermostat.maximum-thermostat.minimum))),0,100):0;
  control_patch(page_pixels,climate_positions[active][percent],climate_slider);
  control_patch(page_pixels,climate_buttons[active][0],climate_down);
  control_patch(page_pixels,climate_buttons[active][1],climate_up);
}
static void draw_light_list(uint8_t *target){
  bool any=false,known=false;
  for(int i=0;i<light_count;i++){
    const int v=ha_lights.confirmed(i);
    const int mode=v<0?0:v==0?1:2;
    known|=v>=0;
    any|=v>0;
    control_patch(target,row_labels[v+1][i],row_values[i]);
    control_patch(target,row_modes[mode][i],row_powers[i]);
  }
  control_patch(target,group_modes[any?2:known?1:0],all_lights_button);
}
static int list_hit(int x,int y){
  if(current!=lights)return -2;
  for(int i=0;i<light_count;i++)if(row_powers[i].contains(x,y))return -10-i;
  return all_lights_button.contains(x,y)?-10-light_count:-2;
}
static void list_toggle(int selected){
  bool any=false,known=false;
  for(int i=0;i<light_count;i++){
    if(i!=selected && selected!=light_count)continue;
    const int level=ha_lights.confirmed(i);
    known|=level>=0;any|=level>0;
  }
  if(!known)return;
  for(int i=0;i<light_count;i++)if((i==selected || selected==light_count) && ha_lights.confirmed(i)>=0)
    ha_lights.request(i,any?0:last_on[i]?last_on[i]:std::max(1,fleet.active().bright[i]));
}
#endif
static int scene_matches(){
#ifdef STUDY_LIVE
  int matches=7;
  bool seen=false;
  const auto &profile=fleet.active();
  for(int i=0;i<light_count;i++){
    const int v=ha_lights.confirmed(i);
    if(!profile.members[i] || v<0)continue;
    seen=true;
    if(std::abs(v-profile.soft[i])>2)matches&=~1;
    if(v>2)matches&=~2;
    if(std::abs(v-profile.bright[i])>2)matches&=~4;
  }
  return seen?matches:0;
#else
  return scene>=0?1<<scene:0;
#endif
}
static int painted_scene=-1;
static void scene_fields(){
  painted_scene=scene_matches();
  for(int i=0;i<3;i++)
    draw_patch(preset_modes[i][(painted_scene>>i)&1],preset_buttons[i],false);
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
#ifdef STUDY_LIVE
  if(current==idle)return;
#endif
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
  if(timeline && build_step==2*lamp_steps && levels[0]>=0 && levels[0]==prepared_level && shift==14){
    if(current==lights && dest==light0)playback_direction=0;
    if(current==light0 && dest==lights)playback_direction=1;
  }
  nav.select(current,dest,shift,request_at);
  const bool transition=change && shift && blender && current!=idle && current!=doorbell && dest!=idle && dest!=doorbell && (dest!=home || nav.active());
  if(transition)std::swap(previous_pixels,page_pixels);
  moving=false;
  current=dest;
  ++revision;
  auto &art=pages[current];
  auto *target=page_pixels?page_pixels:scratch;
  if(!target)return;
  const auto *cached=dest==home?room_pixels:dest==lights?lights_pixels:dest==light0?lamp_pixels:nullptr;
  int i=light_index();
  const bool parallel=transition && page_worker && playback_direction<0 && dest!=scenes && nav.can_prepare_endpoint()
#ifdef STUDY_LIVE
      && i<0 && dest!=lights && dest!=home && dest!=media && dest!=climate_page && dest!=display_page && dest!=edit_page && dest!=members_page
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
    if(page_pixels && dest==scenes)scene_fields();
#ifdef STUDY_LIVE
    if(dest==lights)draw_light_list(target);
    if(dest==climate_page || dest==home)climate_field();
    if(dest==edit_page || dest==members_page)edit_fields();
    if(dest==display_page)display_field(screen_level());
    if(dest==media)transport_fields();
    if(i>=0)control_patch(target,detail_modes[levels[i]<0?0:levels[i]==0?1:2],detail_power_button);
#endif
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
#ifdef STUDY_LIVE
  if(dest==idle){
    wake_page=backlight_off_s>0?home:current;
    if(wake_page==home)depth=0;
    dim_since=clock_ms();blanked=backlight_off_s>0;shown_minute=-2;
    show(idle,0);apply_brightness();return;
  }
#endif
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
  if(lux_entity[0])esphome::api::global_api_server->subscribe_home_assistant_state(
      lux_entity,nullptr,[](esphome::StringRef s){
        auto lux=esphome::parse_number<float>(s.str());
        if(!lux || !std::isfinite(*lux) || *lux<0 || adaptive_bright_lux<=adaptive_dark_lux)return;
        const double fraction=std::clamp((std::log1p(*lux)-std::log1p(adaptive_dark_lux))/
                               (std::log1p(adaptive_bright_lux)-std::log1p(adaptive_dark_lux)),0.0,1.0);
        brightness_target=adaptive_min_pct+fraction*(adaptive_max_pct-adaptive_min_pct);
      });
  last_activity=clock_ms();
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
#ifdef STUDY_LIVE
  last_activity=clock_ms();
  if(wake_touch)return;
  if(current==idle){
    wake_touch=true;blanked=false;show(wake_page,0);apply_brightness();return;
  }
#endif
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
#ifdef STUDY_LIVE
    const int hit=list_hit(x,y);
    if(hit!=-2){pressed=hit;root_link=false;}
    const int edit=edit_hit(x,y);
    if(edit!=-2){pressed=edit;root_link=false;}
    const int transport=transport_hit(x,y);
    if(transport!=-2){pressed=transport;root_link=false;}
    if(current==display_page && backlight_slider.contains(x,y))preview_brightness=screen_level();
    if(current==climate_page && thermostat.can_adjust()){
      if(climate_up.contains(x,y))pressed=-80;
      if(climate_down.contains(x,y))pressed=-81;
      climate_drag=climate_slider.contains(x,y);
    }
#endif
  }
  dx=x-x0;dy=y-y0;
#ifdef STUDY_LIVE
  if(preview_brightness>=0){
    preview_brightness=std::clamp(int(std::lround((x-backlight_slider.x)*100./backlight_slider.w)),0,100);
    if(preview_brightness!=shown_brightness){
      display_field(preview_brightness);++revision;blit(0,0,width,height,page_pixels);
    }
    return;
  }
  if(climate_drag){
    if(!thermostat.can_adjust()){climate_drag=false;climate_preview=NAN;return;}
    const float f=std::clamp(float(x-climate_slider.x)/climate_slider.w,0.f,1.f);
    const float next=std::clamp(std::round((thermostat.minimum+f*(thermostat.maximum-thermostat.minimum))/
                                          thermostat.step)*thermostat.step,thermostat.minimum,thermostat.maximum);
    if(next!=climate_preview){climate_preview=next;climate_field();++revision;blit(0,0,width,height,page_pixels);}
    return;
  }
#endif
  if(dragging && i>=0) {
    int value=std::clamp((x-slider.x)*100/slider.w,0,100);
    if(value!=levels[i]){
      const auto start=esp_timer_get_time();
      levels[i]=value;scene=-1;paint_level(value);
      slider_draw_us+=esp_timer_get_time()-start;++slider_updates;
    }
  } else if(pressed!=-2 && current!=idle) {
    bool inside=false;
#ifdef STUDY_LIVE
    inside=list_hit(x,y)==pressed;
    if(pressed<=-100)inside=edit_hit(x,y)==pressed;
    if(pressed<=-120)inside=transport_hit(x,y)==pressed;
    if(current==climate_page){
      if(pressed==-80)inside=climate_up.contains(x,y);
      if(pressed==-81)inside=climate_down.contains(x,y);
    }
#endif
    for(const auto &link:links)
      if(link.page==current && link.dest==pressed && link.area.contains(x,y))inside=true;
    if(!inside)pressed=-2;
  }
}
static void release() {
#ifdef STUDY_LIVE
  last_activity=clock_ms();
  if(wake_touch){wake_touch=false;return;}
  if(preview_brightness>=0){
    manual_brightness=std::clamp(preview_brightness,int(backlight_min),100);
    override_until=clock_ms()+600000;preview_brightness=-1;
    down=false;pressed=-2;apply_brightness();return;
  }
  if(climate_drag){
    thermostat.set(climate_preview);climate_drag=false;climate_preview=NAN;
    thermostat.dirty=true;down=false;pressed=-2;return;
  }
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
      }
#ifdef STUDY_LIVE
      else if(pressed<=-10 && pressed>=-10-light_count)list_toggle(-10-pressed);
      else if(current==climate_page && (pressed==-80 || pressed==-81))
        thermostat.set(thermostat.target+(pressed==-80?1:-1)*thermostat.step);
      else if(pressed<=-100 && pressed>=-101-light_count)edit_scene(-100-pressed);
      else if(pressed<=-120 && pressed>=-124)player.press(static_cast<p4_runtime::MediaClient::Control>(-120-pressed));
#endif
      else go(pressed);
    }
  }
  down=false;dragging=false;pressed=-2;
}
static void ring() {
  bench_demo=false;
#ifdef STUDY_LIVE
  climate_drag=false;climate_preview=NAN;preview_brightness=-1;
  if(current==idle){blanked=false;show(wake_page,0);}
  last_activity=clock_ms();
#endif
  down=false;dragging=false;pressed=-2;
  if(current!=doorbell)go(doorbell);
#ifdef STUDY_LIVE
  apply_brightness();
#endif
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
  const auto now=clock_ms();
  static int64_t previous=now;
  brightness_now+=(brightness_target-brightness_now)*(adaptive_transition_s>0?
      1-std::exp(-3*std::min(2.0,(now-previous)/1000.)/adaptive_transition_s):1);
  previous=now;
  if(!down && !moving && !bench_demo && !wake_touch && current!=doorbell && current!=idle &&
     idle_timeout_s>0 && now-last_activity>=idle_timeout_s*1000){
    wake_page=current;dim_since=now;shown_minute=-2;show(idle,0);
    ESP_LOGI("study","Timed standby");
  }
  if(current==idle && !blanked){
    if(backlight_off_s>0 && now-dim_since>=backlight_off_s*1000){
      blanked=true;wake_page=home;depth=0;
      ESP_LOGI("study","Timed screen off");
    }else if(minutes_now && page_pixels){
      const int minutes=minutes_now();
      if(minutes!=shown_minute){
        int digits[]={minutes/600,minutes/60%10,0,minutes%60/10,minutes%10};
        for(int i=0;i<5;i++)control_patch(page_pixels,clock_glyphs[minutes<0?10:digits[i]][i],clock_slots[i]);
        ++revision;blit(0,0,width,height,page_pixels);shown_minute=minutes;
      }
    }
  }
  apply_brightness();
  ha_lights.tick();
  player.tick();
  if(player.dirty && !moving && !down){
    player.dirty=false;
    if(current==media && page_pixels){transport_fields();++revision;blit(0,0,width,height,page_pixels);}
  }
  if(current==display_page && page_pixels && !down && !moving && screen_level()!=shown_brightness){
    display_field(screen_level());++revision;blit(0,0,width,height,page_pixels);
  }
  thermostat.tick();
  if(thermostat.dirty && !down && !moving){
    thermostat.dirty=false;
    if(current==home || current==climate_page){climate_field();++revision;blit(0,0,width,height,page_pixels);}
  }
  const bool updated=fleet.tick(ha_lights.receiving());
  const int result=fleet.result();
  if(result){
    edit_waiting=false;edit_feedback=result<0?2:edit_slot<2?3+edit_count:0;
    feedback_until=now+4000;
  }
  const bool expired=!edit_waiting && edit_slot>=0 && now>=feedback_until;
  if(expired){edit_slot=-1;edit_feedback=0;}
  if(result || updated || expired)refresh_edit();
  if(!moving && !down){
    bool list_changed=false;
    for(int i=0;i<light_count;i++)if(live_dirty[i]){
      live_dirty[i]=false;
      levels[i]=ha_lights.confirmed(i);
      list_changed=true;
      if(i==light_index()){
        control_patch(page_pixels,detail_modes[levels[i]<0?0:levels[i]==0?1:2],detail_power_button);
        ++revision;
        paint_level(levels[i]);
      }
    }
    if(list_changed && lights_pixels){
      draw_light_list(lights_pixels);
      scanout.invalidate_lamp();
      prepared_level=-2;
      if(current==lights){
        memcpy(page_pixels,lights_pixels,page_bytes);
        ++revision;blit(0,0,width,height,page_pixels);
      }
    }
    if(current==scenes && scene_matches()!=painted_scene){
      scene_fields();++revision;blit(0,0,width,height,page_pixels);
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
