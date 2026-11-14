#pragma once
#include "study_assets.h"
#ifdef STUDY_LZ4_ARTWORK
#include "study_lz4/lz4.h"
#endif
#ifdef STUDY_IDENTIFY
#include "identify_assets.h"
#endif
#if __has_include("live_runtime/study_profile.h")
#define STUDY_LIVE
#include "control_art.h"
#include "media_art.h"
#include "text_renderer.h"
#include "live_runtime/study_profile.h"
#ifdef STUDY_CARD_ART
#include "live_runtime/card_lights_page.h"
#include "live_runtime/card_routes.h"
#ifdef STUDY_CARD_FIELDS
#include "live_runtime/card_text.h"
#include "live_runtime/card_presets_page.h"
#ifdef STUDY_CARD_SPEAKERS
#include "live_runtime/card_speaker_page.h"
#ifdef STUDY_CARD_PLAYER
#include "live_runtime/card_player.h"
#ifdef STUDY_CARD_MOTION_GEOMETRY
#include "live_runtime/card_motion_geometry.h"
#endif
#ifdef STUDY_CARD_BELL
#include "live_runtime/card_bell.h"
#endif
#ifdef STUDY_CARD_SETTINGS
#include "live_runtime/card_settings.h"
#ifdef STUDY_CARD_DIAGNOSTICS
#include "live_runtime/card_diagnostics.h"
#endif
#endif
#ifdef STUDY_CARD_LIBRARY
#include "live_runtime/card_library.h"
#ifdef STUDY_CARD_OVERLAYS
#include "live_runtime/card_overlay.h"
#ifdef STUDY_CARD_EDITOR
#include "live_runtime/card_editor.h"
#endif
#endif
#ifdef STUDY_CARD_WIFI
#include "live_runtime/card_wifi.h"
#endif
#endif
#endif
#endif
#endif
#endif
#ifdef STUDY_BENCH_TEST
#include "esp_rom_crc.h"
#endif
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
static int64_t identify_until=0;
static int identify_phase=-1;
static int screen_level(){
  if(lux_entity[0] && clock_ms()>=override_until)
    return std::clamp(int(std::lround(brightness_now)),1,100);
  return manual_brightness;
}
static void apply_brightness(){
  const int normal=screen_level();
  const int value=clock_ms()<identify_until?100:
    blanked?0:current==idle?std::max(lux_entity[0]?1:10,int(std::lround(normal*.25))):normal;
  if(value!=applied_brightness && set_light_level && set_light_level(value)){
    applied_brightness=value;
    ESP_LOGD("study","Backlight %d%%",value);
  }
}
#endif
constexpr int width=720, height=1280, page_bytes=width*height*2;
static uint8_t *room_pixels, *page_pixels, *previous_pixels, *mixed_pixels, *lights_pixels, *lamp_pixels;
static bool light_list_cached;
#ifdef STUDY_LIVE
static void control_patch(uint8_t *target,const Sprite &s,const Rect &area);
#endif
static Scanout scanout;
#ifdef STUDY_ARCHITECTURAL_ONLY
static constexpr int selected_theme=2;
static int card_mode=0;
#endif
#ifdef STUDY_CARD_ART
static CardArt card_frames_file,card_levels_file;
static CardScreen card_screens;
static CardLightControls card_sliders;
static CardLightsPage card_lights_page(card_screens,card_sliders);
static bool card_page_visible=false,card_finger=false,card_switching=false;
static int card_theme=0;
static int card_mode=0;
static CardPage card_page=CardPage::lights;
#ifdef STUDY_CARD_FIELDS
static CardArt card_field_file,card_preset_file;
static CardText card_text;
static CardPresetsPage card_presets;
#ifdef STUDY_CARD_SPEAKERS
static CardArt card_speaker_file;
static CardSpeakerPage card_speakers;
#ifdef STUDY_CARD_PLAYER
static CardArt card_player_file;
static bool theme_picker_open=false;
static int selected_theme=2;
#ifdef STUDY_CARD_BELL
static CardArt card_bell_file;
static bool card_bell_active=false;
static const BellView &bell_view(){return card_bell_views[selected_theme*6+card_mode];}
#endif
static int card_travel=14;
static bool decoded_card_endpoint=false;
#ifdef STUDY_CARD_SETTINGS
static CardArt card_settings_file;
static uint8_t *settings_scroll_pixels=nullptr;
static uint8_t *settings_tail=nullptr;
static int settings_offset=0,settings_down_offset=0;
#endif
#ifdef STUDY_CARD_LIBRARY
static CardArt card_library_file;
static CardText card_library_text;
#ifdef STUDY_CARD_OVERLAYS
static CardArt card_overlay_file;
static CardText card_overlay_text;
static int open_card_light=-1;
static bool paint_card_detail(int i,uint8_t *pixels);
static bool paint_card_strip(int theme,int mode,uint8_t *pixels);
#ifdef STUDY_CARD_EDITOR
static CardArt card_editor_file;
static bool paint_card_editor(bool members,uint8_t *pixels);
#endif
#endif
#ifdef STUDY_CARD_WIFI
static CardArt card_wifi_file;
static CardText card_wifi_text;
static bool card_network_open=false;
static bool paint_card_network();
#endif
#endif
#endif
#endif
static std::string (*card_date_now)();
static int card_scene_mask=-1;
static int card_minute=-2;
static std::string card_date;
static bool card_wake=false,card_ring_return=false;
#endif
enum class CardState {idle,loading,ready,failed};
static std::atomic<CardState> card_state{CardState::idle};
static bool card_assets_ready(){
  auto state=card_state.load();
  if(state==CardState::ready)return true;
  if(state==CardState::loading)return false;
  static int64_t retry_at=0;
  if(clock_ms()<retry_at)return false;
  retry_at=clock_ms()+30000;
  card_state.store(CardState::loading);
  if(xTaskCreate([](void*){
        bool ready=card_frames_file.mount() && card_screens.attach(card_frames_file) && card_sliders.attach(card_levels_file)
#ifdef STUDY_CARD_FIELDS
          && card_text.attach(card_field_file) && card_presets.attach(card_preset_file)
#ifdef STUDY_CARD_SPEAKERS
          && card_speakers.attach(card_speaker_file)
#ifdef STUDY_CARD_PLAYER
          && card_player_file.open(card_player_path,card_player_size,card_player_sha)
#ifdef STUDY_CARD_BELL
          && card_bell_file.open(card_bell_path,card_bell_size,card_bell_sha)
#endif
#ifdef STUDY_CARD_SETTINGS
          && card_settings_file.open(card_settings_path,card_settings_size,card_settings_sha)
#endif
#ifdef STUDY_CARD_LIBRARY
          && card_library_file.open(card_library_path,card_library_size,card_library_sha)
#ifdef STUDY_CARD_OVERLAYS
          && card_overlay_file.open(card_overlay_path,card_overlay_size,card_overlay_sha)
#ifdef STUDY_CARD_EDITOR
          && card_editor_file.open(card_editor_path,card_editor_size,card_editor_sha)
#endif
#endif
#ifdef STUDY_CARD_WIFI
          && card_wifi_file.open(card_wifi_path,card_wifi_size,card_wifi_sha)
#endif
#endif
#endif
#endif
#endif
          ;
#ifdef STUDY_CARD_LIBRARY
        if(ready)ready=card_library_text.use_bank(card_library_file,library_glyph_offset,library_glyph_count);
#ifdef STUDY_CARD_OVERLAYS
        if(ready)ready=card_overlay_text.use_bank(card_overlay_file,overlay_glyph_offset,overlay_glyph_count);
#endif
#ifdef STUDY_CARD_WIFI
        if(ready)ready=card_wifi_text.use_bank(card_wifi_file,wifi_glyph_offset,wifi_glyph_count);
#endif
#endif
        card_state.store(ready?CardState::ready:CardState::failed);
        ESP_LOGI("study_card","Theme artwork %s",ready?"ready":"unavailable");
        vTaskDelete(nullptr);
      },"study_card",6144,nullptr,1,nullptr)!=pdPASS){
    ESP_LOGW("study_card","Could not allocate the artwork verification task");
    card_state.store(CardState::failed);
  }
  return false;
}
#endif
#if defined(STUDY_LIVE) && __has_include("palette_assets.h")
}
#define STUDY_PALETTE_PICKER
#include "live_runtime/palette_renderer.h"
namespace study {
static PaletteRenderer palette;
static bool picker_open=false;
static void restore_media_colours(uint8_t *frame,const Rect &paint);
#endif
static uint32_t revision=1;
static bool blit(int x,int y,int w,int h,uint8_t *pixels,int stride=0) {
#ifdef STUDY_CARD_ART
  if(card_switching)return true;
#endif
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
  if(seed)scanout.copy_pixels(slot->pixels,page_pixels,page_bytes);
  if(full)scanout.copy_pixels(slot->pixels,pixels,page_bytes);
  else if(!seed || !stride) {
    for(int row=0;row<h;row++)
      memcpy(slot->pixels+2*((y+row)*width+x),pixels+2*row*(stride?stride:w),2*w);
  }
  slot->page=revision;
  slot->lamp_background=current==lights || current==light0;
#ifdef STUDY_PALETTE_PICKER
  if(!picker_open && current!=doorbell && palette.selection()
#ifdef STUDY_CARD_ART
     && !card_page_visible
#ifdef STUDY_CARD_WIFI
     && !card_network_open
#endif
#endif
  ){
    if(!full && !seed && stride)
      for(int row=0;row<h;row++)memcpy(slot->pixels+2*((y+row)*width+x),pixels+2*row*stride,2*w);
    const Rect paint=full || seed?Rect{0,0,width,height}:Rect{x,y,w,h};
    palette.render(reinterpret_cast<uint16_t*>(slot->pixels),paint.x,paint.y,paint.w,paint.h,true);
    restore_media_colours(slot->pixels,paint);
    auto &button=palette_buttons[0];
    if(current==display_page && (full || seed || (y<button.y+button.h && y+h>button.y)))
      palette.label(reinterpret_cast<uint16_t*>(slot->pixels),scratch);
  }
#endif
  return scanout.present(slot,seed?0:y,seed?height:y+h);
}
static ppa_client_handle_t blender;
static int64_t motion_start;
static int travel, motion_frames, motion_height;
static bool moving;
static bool palette_motion=false;
static esphome::HighFrequencyLoopRequester motion_loop;
static void await_page();
static bool unpack(const Sprite &s,uint8_t *out);
}
#include "navigation.h"
namespace study {
static uint8_t *page_buffer() {
  return static_cast<uint8_t*>(heap_caps_aligned_alloc(128,page_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
}
static bool unpack(const Sprite &s,uint8_t *out) {
  if(s.size>>31){
    if(!out)return false;
    auto *strip=static_cast<uint8_t*>(heap_caps_malloc(32*s.h,MALLOC_CAP_8BIT));
    if(!strip)return false;
    bool ok=true;
    for(int x=0;x<s.w && ok;x+=16){
      uint16_t id;memcpy(&id,artwork+s.offset+2*(x/16),sizeof(id));
      const auto &tile=digit_strips[id];
      const size_t bytes=2*tile.w*tile.h;
      ok=tinfl_decompress_mem_to_mem(strip,bytes,artwork+tile.offset,tile.size,1)==bytes;
      if(ok)for(int y=0;y<s.h;y++)memcpy(out+2*(y*s.w+x),strip+2*y*tile.w,2*tile.w);
    }
    heap_caps_free(strip);return ok;
  }
  const size_t size=size_t(s.w)*s.h*2;
#ifdef STUDY_LZ4_ARTWORK
  if(s.size&(1u<<30)){
    const unsigned compressed_size=s.size&~(1u<<30);
    return out && s.offset<=artwork_bytes && compressed_size<=artwork_bytes-s.offset &&
      LZ4_decompress_safe(reinterpret_cast<const char*>(artwork+s.offset),
                          reinterpret_cast<char*>(out),compressed_size,size)==int(size);
  }
#endif
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
    if(worker_source)scanout.copy_pixels(worker_target,worker_source,page_bytes);
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
      auto &r=i?slider_paint:reading;
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
    scanout.copy_pixels(slot->pixels,page_pixels,page_bytes);
    if(!scanout.present(slot,0,height))return;
    slot->lamp_background=false;slot->page=revision;moving=false;++motion_frames;
    ESP_LOGI("study","Cached lamp transition: %d frames in %lld ms",motion_frames,clock_ms()-motion_start);
    return;
  }
  const bool seed=!slot->lamp_background;
  if(seed)scanout.copy_pixels(slot->pixels,lights_pixels,page_bytes);
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
  uint32_t offset=s.offset,size=s.size;
  if(size&(1u<<30)){
    struct Dictionary {uint32_t offset,length,bytes;} dict;
    memcpy(&dict,control_art+offset,sizeof(dict));
    static uint8_t *patterns=nullptr;
    static uint32_t cached=UINT32_MAX,capacity=0;
    if(cached!=dict.offset){
      if(capacity<dict.bytes){
        heap_caps_free(patterns);cached=UINT32_MAX;capacity=0;
        patterns=static_cast<uint8_t*>(heap_caps_malloc(dict.bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
        if(!patterns)return;
        capacity=dict.bytes;
      }
      if(tinfl_decompress_mem_to_mem(patterns,dict.bytes,control_art+dict.offset,dict.length,1)!=dict.bytes)return;
      cached=dict.offset;
    }
    const size_t count=(bytes+15)/16;
    if(tinfl_decompress_mem_to_mem(scratch,2*count,control_art+offset+sizeof(dict),
        (size&0x3fffffff)-sizeof(dict),1)!=2*count)return;
    const auto *codes=reinterpret_cast<const uint16_t*>(scratch);
    for(int y=0;y<s.h;y++){
      auto *dst=reinterpret_cast<uint16_t*>(target)+(area.y+y)*width+area.x;
      for(int x=0;x<s.w;x++){
        const int n=y*s.w+x;
        dst[x]=reinterpret_cast<const uint16_t*>(patterns)[8*codes[n/8]+n%8];
      }
    }
    return;
  }
  struct Crop {uint32_t offset,size;uint16_t x,y,w,h;} crop{};
  const bool cropped=(size>>31)!=0;
  if(cropped){
    memcpy(&crop,control_art+offset,sizeof(crop));offset=crop.offset;size=crop.size;
  }
  if(tinfl_decompress_mem_to_mem(scratch,bytes,control_art+offset,size,1)!=bytes)return;
  for(int y=0;y<s.h;y++)
    memcpy(target+2*((area.y+y)*width+area.x),scratch+2*y*s.w,2*s.w);
  if(cropped){
    const size_t n=2u*crop.w*crop.h;
    if(tinfl_decompress_mem_to_mem(scratch,n,control_art+s.offset+sizeof(crop),
       (s.size&0x7fffffff)-sizeof(crop),1)!=n)return;
    for(int y=0;y<crop.h;y++)
      memcpy(target+2*((area.y+crop.y+y)*width+area.x+crop.x),scratch+2*y*crop.w,2*crop.w);
  }
}
static void display_field(int level){
  shown_brightness=level;
  control_patch(page_pixels,backlight_modes[level][0],backlight_rail);
  control_patch(page_pixels,backlight_modes[level][1],backlight_value);
}
static bool volume_open=false;
static bool queue_open=false;
static bool library_open=false;
static int library_mode=0,library_scroll=0,library_down_scroll=0;
static constexpr int thumbnail_side=96,thumbnail_slots=12;
struct Thumbnail {std::string url;uint16_t *pixels=nullptr;uint32_t used=0;bool ready=false;};
static Thumbnail thumbnails[thumbnail_slots];
static int thumbnail_job=-1;static uint32_t thumbnail_stamp=0;
static void load_library_thumbnail();
static void label(const TextArea &field,const char *value);
static void show(int dest,int shift);
#ifdef STUDY_CARD_PLAYER
static bool show_card_root(int dest,int theme,int mode);
static bool show_card_player(int theme,int mode);
static bool show_card_options(int theme,int mode,CardPage page);
#endif
// The embedded panel has no CSS compositor. Exercise the equivalent native
// list operations and report completed framebuffer presentations.
static int diagnostic_pass=-1,diagnostic_frames=0,diagnostic_offset=0;
static int64_t diagnostic_start=0;
static int diagnostic_rates[6];
static constexpr const char *diagnostic_cases[]={"baseline","unpromoted list","no content-vis","no thumbnails","no text","flat rows"};
#ifdef STUDY_CARD_LIBRARY
static bool card_diagnostic_frame();
#endif
// A scroll moves the existing list pixels. Repaint only the newly exposed
// band, using the kiosk's own four-row RGB565 dither as its ground.
static uint16_t library_ground[2][4][library_list.w];
static int8_t library_ground_ok[2]={-1,-1};
// A folder and a track use the same two backgrounds on every row. Keep
// decoded copies while browsing so exposing a few scanlines doesn't inflate
// an entire tile for each item. Keep the uncached path for tight PSRAM.
static uint8_t *library_background[2]={nullptr,nullptr};
static int library_cache_mode=-1;
#ifdef STUDY_CARD_LIBRARY
static uint8_t *card_library_background=nullptr;
static int card_library_index=-1;
#endif
static void release_library_backgrounds(){
  for(auto &entry:library_background){heap_caps_free(entry);entry=nullptr;}
  library_cache_mode=-1;
#ifdef STUDY_CARD_LIBRARY
  heap_caps_free(card_library_background);card_library_background=nullptr;card_library_index=-1;
#endif
}
static const uint8_t *library_tile(int mode,int variant,size_t bytes){
  if(library_cache_mode!=mode){release_library_backgrounds();library_cache_mode=mode;}
  auto &cached=library_background[variant%2];
  if(cached)return cached;
  if(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)>bytes+256*1024)
    cached=static_cast<uint8_t*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  auto *out=cached?cached:scratch;
  const auto &art=library_art[variant];
  if(tinfl_decompress_mem_to_mem(out,bytes,text_art+art[0],art[1],1)==bytes)return out;
  heap_caps_free(cached);cached=nullptr;return nullptr;
}
static void paint_library(int movement=0){
  const int mode=library_mode,cols=library_steps[mode][0],step=library_steps[mode][1];
  const auto &v=library_list;
  int top=v.y,end=v.y+v.h;
  auto *pixels=reinterpret_cast<uint16_t*>(page_pixels);
  const size_t row_bytes=size_t(v.w)*sizeof(*pixels);
  if(movement && std::abs(movement)<v.h && library_ground_ok[mode]==1 && !library.dirty && !*library.message){
    const int delta=std::abs(movement);
    for(int n=0;n<v.h-delta;n++){
      const int y=movement>0?top+n:end-1-n;
      memcpy(pixels+y*width+v.x,pixels+(y+movement)*width+v.x,row_bytes);
    }
    if(movement>0)top=end-delta;else end=top+delta;
    for(int y=top;y<end;y++)memcpy(pixels+y*width+v.x,library_ground[mode][(y-v.y)%4],row_bytes);
    // The gutters stay fixed to the glass, while the dither inside a card
    // moves with that card. Recover the original phase in the exposed gaps.
    if(movement%4){
      const auto &tile=library_tiles[mode*2];
      const int spacing=cols==1?tile.w:int(library_steps[mode][2]);
      for(int y=v.y;y<v.y+v.h;y++){
        if(y>=top && y<end)continue;
        const int position=y-v.y+library_scroll;
        const size_t first=size_t(position/step)*cols;
        int last_x=0;
        const auto *ground=library_ground[mode][(y-v.y)%4];
        auto *dst=pixels+y*width+v.x;
        if(position%step<tile.h)for(int col=0;col<cols;col++){
          const size_t index=first+col;
          if(index<library.first || index-library.first>=library.items.size())continue;
          const int x=col*spacing;
          if(x>last_x)memcpy(dst+last_x,ground+last_x,2*(x-last_x));
          last_x=x+tile.w;
        }
        if(last_x<v.w)memcpy(dst+last_x,ground+last_x,2*(v.w-last_x));
      }
    }
  }else{
    text_background(page_pixels,width,scratch,{0,0,width,height},library_bases[mode][0],library_bases[mode][1]);
    if(library_ground_ok[mode]<0){
      for(int y=0;y<4;y++)memcpy(library_ground[mode][y],pixels+(v.y+y)*width+v.x,row_bytes);
      library_ground_ok[mode]=1;
      for(int y=4;y<v.h;y++)if(memcmp(library_ground[mode][y%4],pixels+(v.y+y)*width+v.x,row_bytes)){
        library_ground_ok[mode]=0;break;
      }
    }
    label(library_title,library.folders.empty()?"Library":library.folders.back().title.c_str());
    std::string crumb="Library";for(const auto &f:library.folders)crumb+="  ›  "+f.title;
    label(library_crumb,crumb.c_str());
  }
  if(*library.message){
    auto field=library_crumb;field.rect.y=v.y+20;
    text_field(page_pixels,width,scratch,field,library.message,v.y,v.y+v.h);return;
  }
  for(size_t i=0;i<library.items.size();i++){
    const auto &item=library.items[i];const int variant=2*mode+(item.expand?0:1);
    const auto &ref=library_tiles[variant];
    const int x=v.x+(i%cols)*library_steps[mode][2];
    const int y=v.y+int((library.first+i)/cols)*step-library_scroll;
    if(y>=end || y+ref.h<=top)continue;
    const size_t bytes=2*ref.w*ref.h;
    const auto *tile=library_tile(mode,variant,bytes);
    if(!tile)continue;
    for(int row=std::max(0,top-y);row<ref.h && row+y<end;row++)
      memcpy(page_pixels+2*((y+row)*width+x),tile+2*row*ref.w,2*ref.w);
    if(item.expand && item.category!="directory"){
      auto icon=library_note_rects[mode];icon.x+=x-library_tiles[2*mode].x;icon.y+=y-library_tiles[2*mode].y;
      const auto &artwork=library_notes[mode];
      const size_t n=2u*icon.w*icon.h;
      if(tinfl_decompress_mem_to_mem(scratch,n,text_art+artwork[0],artwork[1],1)==n)
        for(int j=std::max(0,top-icon.y);j<icon.h && icon.y+j<end;j++)
          memcpy(page_pixels+2*((icon.y+j)*width+icon.x),scratch+2*j*icon.w,2*icon.w);
    }
    if(!item.thumbnail.empty())for(auto &thumb:thumbnails)if(thumb.ready && thumb.url==item.thumbnail){
      auto icon=library_note_rects[mode];icon.x+=x-library_tiles[2*mode].x;icon.y+=y-library_tiles[2*mode].y;
      for(int j=std::max(0,top-icon.y);j<icon.h && icon.y+j<end;j++){
        auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(icon.y+j)*width+icon.x;
        for(int col=0;col<icon.w;col++)dst[col]=thumb.pixels[(j*thumbnail_side/icon.h)*thumbnail_side+col*thumbnail_side/icon.w];
      }
      thumb.used=++thumbnail_stamp;break;
    }
    auto field=[&](TextArea area,const std::string &value){
      area.rect.x+=x-ref.x;area.rect.y+=y-ref.y;
      text_field(page_pixels,width,scratch,area,value.c_str(),top,end,false);
    };
    field(library_name[variant],item.title);field(library_type[variant],item.category);
  }
}
#ifndef STUDY_ARCHITECTURAL_ONLY
static void diagnostic_scroll_frame(){
  if(diagnostic_pass<0 || diagnostic_pass>=6)return;
#ifdef STUDY_CARD_LIBRARY
  if(selected_theme<2){card_diagnostic_frame();return;}
#endif
  const auto &r=library_tiles[2];
  const auto &v=library_list;
  const int step=library_steps[1][1],first=diagnostic_offset/step;
  const int last=std::min(200,first+v.h/step+2);
  const size_t bytes=2*r.w*r.h;
  const auto &art=library_art[2];
  auto *row_cache=previous_pixels;
  const uint16_t background=reinterpret_cast<uint16_t*>(page_pixels)[(v.y-1)*width+v.x];
  if(!diagnostic_frames){
    text_background(page_pixels,width,scratch,{0,0,width,height},library_bases[1][0],library_bases[1][1]);
    label(library_title,"Scroll test");
    char crumb[64];snprintf(crumb,sizeof(crumb),"%s  (%d of 6)",diagnostic_cases[diagnostic_pass],diagnostic_pass+1);
    label(library_crumb,crumb);
    if(tinfl_decompress_mem_to_mem(row_cache,bytes,text_art+art[0],art[1],1)!=bytes){diagnostic_pass=-1;return;}
    diagnostic_start=clock_ms();
  }
  auto *pixels=reinterpret_cast<uint16_t*>(page_pixels);
  for(int y=v.y;y<v.y+v.h;y++)std::fill_n(pixels+y*width+v.x,v.w,background);
  for(int i=diagnostic_pass==2?0:first;i<(diagnostic_pass==2?200:last);i++){
    const int y=v.y+i*step-diagnostic_offset;
    char title[20];snprintf(title,sizeof(title),"Row %d",i);
    if(y+r.h<=v.y || y>=v.y+v.h)continue;
    if(diagnostic_pass==1 && tinfl_decompress_mem_to_mem(row_cache,bytes,text_art+art[0],art[1],1)!=bytes)continue;
    for(int j=std::max(0,v.y-y);j<r.h && j+y<v.y+v.h;j++){
      auto *dest=pixels+(j+y)*width+v.x;
      if(diagnostic_pass==5)std::fill_n(dest,r.w,0x18e4);
      else{
        memcpy(dest,row_cache+2*j*r.w,2*r.w);
        if(diagnostic_pass==3)std::fill_n(dest+12,72,dest[90]);
      }
    }
    if(diagnostic_pass!=4){
      for(int f=0;f<2;f++){
        auto a=f?library_type[2]:library_name[2];a.rect.y+=y-r.y;
        text_field(page_pixels,width,scratch,a,f?"test":title,v.y,v.y+v.h,false);
      }
    }
  }
  ++revision;if(blit(0,0,width,height,page_pixels))++diagnostic_frames;
  diagnostic_offset=(diagnostic_offset+7)%(200*step-v.h);
  const auto elapsed=clock_ms()-diagnostic_start;
  if(elapsed<2500)return;
  diagnostic_rates[diagnostic_pass]=std::lround(diagnostic_frames*1000./elapsed);
  ESP_LOGI("study","Scroll test %s %d fps",diagnostic_cases[diagnostic_pass],diagnostic_rates[diagnostic_pass]);
  ++diagnostic_pass;diagnostic_frames=0;
  if(diagnostic_pass!=6)return;
  const int mode=library_mode;
  text_background(page_pixels,width,scratch,{0,0,width,height},library_bases[mode][0],library_bases[mode][1]);
  const auto &result_art=diagnostic_results[mode];
  if(tinfl_decompress_mem_to_mem(scratch,page_bytes,text_art+result_art[0],result_art[1],1)==page_bytes){
    for(size_t j=0;j<page_bytes/4;j++)reinterpret_cast<uint32_t*>(page_pixels)[j]^=reinterpret_cast<uint32_t*>(scratch)[j];
  }
  for(int i=0;i<6;i++){
    char result[80];const int delta=std::lround(100.*(diagnostic_rates[i]-diagnostic_rates[0])/std::max(1,diagnostic_rates[0]));
    if(i)snprintf(result,sizeof(result),"%d fps · %+d%%  %s",diagnostic_rates[i],delta,std::abs(delta)<25?"(within noise)":"← this one matters");
    else snprintf(result,sizeof(result),"%d fps · baseline",diagnostic_rates[i]);
    label(diagnostic_result_n[mode][i],diagnostic_cases[i]);label(diagnostic_result_s[mode][i],result);
  }
  ++revision;blit(0,0,width,height,page_pixels);
}
#endif
static bool speakers_open=false,speakers_dirty=false,transfer_busy=false;
static int speaker_scroll=0,speaker_down_scroll=0,speaker_max_scroll=0;
static uint32_t transfer_serial=0;
static int64_t transfer_until=0;
static const char *transfer_status=nullptr;
static int speaker_variant(int i){
  if(i==selected_speaker)return 0;
  return !players[i].available?1:players[i].player_type.empty()?2:3;
}
static bool can_transfer(int i){
  const auto &src=player(),&dst=players[i];
  return !transfer_busy && i!=selected_speaker && (src.playing || src.paused) &&
    !src.player_type.empty() && !src.queue.empty() && dst.available &&
    !dst.player_type.empty() && dst.queue!=src.queue;
}
static bool cover_ready=false;
static int cover_speaker=-1;
static std::string cover_picture;
static void select_speaker(int i){
  selected_speaker=i;player().dirty=true;
  cover_ready=cover_speaker==i && cover_picture==player().picture;
  speakers_open=false;
}
static void transfer_speaker(int i){
  if(!can_transfer(i))return;
#ifdef STUDY_BENCH_TEST
  player().last_service="music_assistant.transfer_queue";
  select_speaker(i);
#else
  auto *api=esphome::api::global_api_server;
  if(!api->is_connected_with_state_subscription())return;
  using esphome::StringRef;
  esphome::api::HomeassistantActionRequest req;
  req.service=StringRef("music_assistant.transfer_queue");req.data.init(3);
  auto add=[&](const char *key,const char *value){
    auto &kv=req.data.emplace_back();kv.key=StringRef(key);kv.value=StringRef(value);
  };
  add("entity_id",speaker_ids[i]);add("source_player",speaker_ids[selected_speaker]);
  add("auto_play",player().playing?"true":"false");
  req.call_id=0x80000000u|++transfer_serial;
  transfer_busy=true;transfer_until=clock_ms()+30000;
  transfer_status="Transferring…";speakers_dirty=true;
  api->register_action_response_callback(req.call_id,[i,serial=transfer_serial](const esphome::api::ActionResponse &r){
    if(serial!=transfer_serial || !transfer_busy)return;
    transfer_busy=false;speakers_dirty=true;
    if(r.is_success()){
      transfer_status=nullptr;
      if(speakers_open){select_speaker(i);show(media,0);}
    }
    else transfer_status="Transfer not confirmed. Check the speakers before retrying.";
  });
  api->send_homeassistant_action(req);
#endif
}
static uint16_t *cover_pixels=nullptr;
static bool mini_art_enabled=default_mini_art;
static bool diagnostics_enabled=diagnostic_default;
#ifdef STUDY_PALETTE_PICKER
static void restore_media_colours(uint8_t *frame,const Rect &paint){
  if(current!=media && current!=home)return;
  auto restore=[&](const Rect &image,int top,int bottom){
    const int x=std::max(paint.x,image.x),end_x=std::min(paint.x+paint.w,image.x+image.w);
    const int y=std::max({paint.y,image.y,top}),end_y=std::min({paint.y+paint.h,image.y+image.h,bottom});
    if(x>=end_x)return;
    for(int row=y;row<end_y;row++){
      const auto offset=2*(row*width+x);
      memcpy(frame+offset,page_pixels+offset,2*(end_x-x));
    }
  };
  if(library_open && current==media){
    const int cols=library_steps[library_mode][0],step=library_steps[library_mode][1];
    const int first=std::max(0,library_scroll/step*cols-int(library.first));
    const auto &tile=library_tiles[2*library_mode];
    for(size_t i=first;i<library.items.size();i++){
      const int y=library_list.y+int((library.first+i)/cols)*step-library_scroll;
      if(y>=library_list.y+library_list.h)break;
      const auto &url=library.items[i].thumbnail;
      if(url.empty() || !std::any_of(thumbnails,thumbnails+thumbnail_slots,[&](const Thumbnail &t){return t.ready && t.url==url;}))continue;
      Rect icon=library_note_rects[library_mode];
      icon.x+=library_list.x+(i%cols)*library_steps[library_mode][2]-tile.x;
      icon.y+=y-tile.y;
      restore(icon,library_list.y,library_list.y+library_list.h);
    }
  }else if(cover_ready && !queue_open && !speakers_open){
    if(current==media)restore(album_rect,0,height);
    else if(player().playing && mini_art_enabled)restore(mini_album_rect,0,height);
  }
}
#endif
static int observed_touches=0;
static int refresh_fps=0;
static float display_refresh_hz=0;
static bool ha_connected(){
  const auto *api=esphome::api::global_api_server;
  return api && api->is_connected_with_state_subscription() && ha_lights.receiving();
}
static void copy_badge_background(Scanout::Slot *slot,bool save){
  constexpr size_t bytes=2*width*32;
  if(save)memcpy(slot->overlay_background,slot->pixels,bytes);
  else memcpy(slot->pixels,slot->overlay_background,bytes);
  slot->has_overlay=save;
}
static void draw_diagnostic_badges(Scanout::Slot *slot,int &first_y,int &end_y){
#if defined(STUDY_CARD_FIELDS) && !defined(STUDY_CARD_DIAGNOSTICS)
  if(card_page_visible)return;
#endif
  if(!diagnostics_enabled || blanked || current==doorbell || !scratch || clock_ms()<identify_until)return;
  if(!slot->overlay_background){
    const size_t size=2*width*32;
    slot->overlay_background=static_cast<uint8_t*>(heap_caps_malloc(size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!slot->overlay_background)return;
  }
  copy_badge_background(slot,true);
  uint8_t glyph_scratch[2048];
  char rate[24];snprintf(rate,sizeof(rate),"%d fps",refresh_fps);
  const bool online=ha_connected();
#ifdef STUDY_CARD_DIAGNOSTICS
  if(selected_theme<2){
    const auto &v=card_diagnostics_views[selected_theme*6+card_mode];
    auto draw=[&](TextArea field,const DiagLabel &box,const char *value,int align){
      field.rect={box.x,box.y,box.w,box.h};field.baseline=box.baseline;field.spacing=box.spacing;
      field.colour=box.colour;field.align=align;
      text_field(slot->pixels,width,glyph_scratch,field,value,0,height,false);
    };
    draw(online?diag_connection:diag_disconnected,v.badges[online?0:1],online?"connected":"disconnected — retrying",0);
    draw(diag_fps,v.badges[2],rate,2);
    first_y=0;end_y=std::max(end_y,32);return;
  }
#endif
  text_field(slot->pixels,width,glyph_scratch,online?diag_connection:diag_disconnected,online?"connected":"disconnected — retrying",0,height,false);
  text_field(slot->pixels,width,glyph_scratch,diag_fps,rate,0,height,false);
  first_y=std::min(first_y,diag_connection.rect.y);
  end_y=std::max(end_y,diag_connection.rect.y+diag_connection.rect.h);
}
static void measure_refresh(){
  static int64_t previous=0;static uint32_t earlier=0;
  const auto now=clock_ms();const auto epoch=Scanout::Panel::refresh_epoch;
  if(previous && now-previous<1000)return;
  if(previous)display_refresh_hz=(epoch-earlier)*1000./(now-previous);
  refresh_fps=std::lround(scanout.rendered_fps());
  fleet.display_metrics(refresh_fps,display_refresh_hz,applied_brightness);
  earlier=epoch;previous=now;
}
#if defined(STUDY_BENCH_TEST) || defined(STUDY_LIVE_CAPTURE)
static constexpr const char *display_namespace="p4_qa_display";
#else
static constexpr const char *display_namespace="p4_display";
#endif
static void load_display_choice(){
  nvs_handle_t h;
  if(nvs_open(display_namespace,NVS_READONLY,&h)!=ESP_OK)return;
  uint8_t value=0;if(nvs_get_u8(h,"mini",&value)==ESP_OK)mini_art_enabled=value!=0;
  if(nvs_get_u8(h,"diag",&value)==ESP_OK)diagnostics_enabled=value!=0;
  if(nvs_get_u8(h,"libview",&value)==ESP_OK)library_mode=value?1:0;
#ifdef STUDY_CARD_PLAYER
  if(nvs_get_u8(h,"theme",&value)==ESP_OK && value<=2)selected_theme=value;
#endif
  nvs_close(h);
}
static bool save_preference(const char *key,uint8_t enabled){
  nvs_handle_t h;if(nvs_open(display_namespace,NVS_READWRITE,&h)!=ESP_OK)return false;
  const bool ok=nvs_set_u8(h,key,enabled)==ESP_OK && nvs_commit(h)==ESP_OK;nvs_close(h);
  return ok;
}
#ifdef STUDY_SCREEN_OPTIONS
// A local touch overrides the same server default until that default changes.
// Store the baseline alongside each choice to handle a later offline restart.
static bool remember_screen(const char *key,uint8_t value,uint8_t base){
  nvs_handle_t h;if(nvs_open(display_namespace,NVS_READWRITE,&h)!=ESP_OK)return false;
  auto base_key=std::string(key)+"_base";
  bool ok=nvs_set_u8(h,key,value)==ESP_OK && nvs_set_u8(h,base_key.c_str(),base)==ESP_OK && nvs_commit(h)==ESP_OK;
  nvs_close(h);return ok;
}
static uint8_t local_screen(const char *key,uint8_t base,uint8_t max){
  nvs_handle_t h;if(nvs_open(display_namespace,NVS_READONLY,&h)!=ESP_OK)return base;
  uint8_t previous=base,value=base;
  auto base_key=std::string(key)+"_base";
  const bool has_base=nvs_get_u8(h,base_key.c_str(),&previous)==ESP_OK;
  bool valid=nvs_get_u8(h,key,&value)==ESP_OK && value<=max && (!has_base || previous==base);
  nvs_close(h);
  if(!has_base || previous!=base)remember_screen(key,valid?value:base,base);
  return valid?value:base;
}
static bool pending_screen_report=false;
static ScreenChoices reported_screen;
static bool pending_mini_art=false;
static void report_screen(bool include_mini=false){
  pending_mini_art|=include_mini;
  std::string json=std::string("{\"theme\":\"")+theme_keys[selected_theme]+"\",\"palette\":\""+
      palette_keys[card_mode]+"\",\"diagnostics\":"+(diagnostics_enabled?"true":"false")+
      ",\"browse_view\":\""+(library_steps[library_mode][0]>1?"tiles":"list")+"\"";
  if(pending_mini_art)json+=std::string(",\"mini_art\":")+(mini_art_enabled?"true":"false");
  json+="}";
  pending_screen_report=fleet.online() && !fleet.submit(decltype(fleet)::Edit::display,json);
  if(!pending_screen_report && fleet.online()){
    reported_screen={uint8_t(selected_theme),uint8_t(card_mode),diagnostics_enabled,library_steps[library_mode][0]>1,mini_art_enabled};
    pending_mini_art=false;
  }
}
#endif
static bool save_display_choice(bool enabled){
#ifdef STUDY_SCREEN_OPTIONS
  const bool ok=remember_screen("mini",enabled,fleet.active().screen.mini_art);
  if(ok){mini_art_enabled=enabled;report_screen(true);}
#else
  const bool ok=save_preference("mini",enabled);
  if(ok)mini_art_enabled=enabled;
#endif
  return ok;
}
#ifdef STUDY_PALETTE_PICKER
static bool choose_palette(int value){
  if(value==palette.selection()){
#ifdef STUDY_SCREEN_OPTIONS
    card_mode=value;
#endif
    return true;
  }
  const int before=palette.selection();
  if(!before)nav.use_palette_memory();
  if(!palette.choose(value,scratch) ||
#ifdef STUDY_SCREEN_OPTIONS
     !remember_screen("palette",value,fleet.active().screen.palette)
#else
     !save_preference("palette",value)
#endif
  ){
    if(!palette.choose(before,scratch))ESP_LOGW("study","Could not restore previous palette");
    if(!before)nav.restore_chunks();
    return false;
  }
  if(!value
#ifdef STUDY_SCREEN_OPTIONS
     && selected_theme==2
#endif
  )nav.restore_chunks();
#ifdef STUDY_SCREEN_OPTIONS
  card_mode=value;report_screen();
#endif
  return true;
}
static void open_palette(){
  if(!palette.picker(page_pixels))return;
  picker_open=true;++revision;blit(0,0,width,height,page_pixels);
}
#endif
static uint32_t cover_generation=0;
static void update_cover();
static void draw_cover(const Rect &r){
  if(!cover_ready || !cover_pixels)return;
  for(int y=0;y<r.h;y++){
    auto *out=reinterpret_cast<uint16_t*>(page_pixels)+(r.y+y)*width+r.x;
    const auto *source=cover_pixels+(y*album_rect.h/r.h)*album_rect.w;
    if(r.w==album_rect.w)memcpy(out,source,r.w*2);
    else for(int x=0;x<r.w;x++)out[x]=source[x*album_rect.w/r.w];
  }
}
static int volume_drag=-1;
static int seek_drag=-1;
static uint8_t *volume_dictionary_pixels=nullptr;
template<size_t N> static void volume_paint(const Rect &r,const uint16_t (&ids)[N]){
  if(!volume_art)return;
  auto &dictionary=volume_dictionary_pixels;
  if(!dictionary){
    dictionary=static_cast<uint8_t*>(heap_caps_malloc(volume_dictionary_size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!dictionary)return;
    if(tinfl_decompress_mem_to_mem(dictionary,volume_dictionary_size,volume_art+volume_dictionary.offset,
         volume_dictionary.size,1)!=volume_dictionary_size){heap_caps_free(dictionary);dictionary=nullptr;return;}
  }
  const auto &base=volume_bases[&r==&volume_popup];
  const size_t size=2*r.w*r.h;
  if(tinfl_decompress_mem_to_mem(scratch,size,volume_art+base.offset,base.size,1)!=size)return;
  for(int y=0;y<r.h;y++)memcpy(page_pixels+2*((r.y+y)*width+r.x),scratch+2*y*r.w,2*r.w);
  for(size_t k=0;k<N;k++){
    const auto &tile=volume_tiles[ids[k]];
    const int x=k*16,w=std::min(16,r.w-x);
    const size_t bytes=2*w*r.h;
    const size_t count=(bytes+15)/16;
    if(tinfl_decompress_mem_to_mem(scratch,2*count,volume_art+tile.offset,tile.size,1)!=2*count)return;
    const auto *codes=reinterpret_cast<const uint16_t*>(scratch);
    for(int y=0;y<r.h;y++){
      auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(r.y+y)*width+r.x+x;
      for(int col=0;col<w;col++){
        const int pixel=y*w+col;
        dst[col]^=reinterpret_cast<const uint16_t*>(dictionary)[8*codes[pixel/8]+pixel%8];
      }
    }
  }
}
static void paint_volume(){
  const int pct=volume_drag>=0?volume_drag:std::max(0,player().volume);
  volume_paint(volume_button,volume_button_tiles[pct]);
  if(volume_open)volume_paint(volume_popup,volume_popup_tiles[pct]);
}
static void label(const TextArea &field,const char *value){text_field(page_pixels,width,scratch,field,value);}
}
#ifdef USE_ESP32_HOSTED
#define STUDY_RENDER_NETWORK
#include "live_runtime/network_screen.h"
#undef STUDY_RENDER_NETWORK
#endif
namespace study {
static void playback_time(const TextArea &area,int seconds){
  char out[24];snprintf(out,sizeof(out),"%d:%02d",seconds/60,seconds%60);label(area,out);
}
static uint16_t interpolate_pixel(uint16_t first,uint16_t second,unsigned weight){
  const unsigned inverse=256-weight;
  return ((((first&0xf81f)*inverse+(second&0xf81f)*weight)>>8)&0xf81f) |
         ((((first&0x07e0)*inverse+(second&0x07e0)*weight)>>8)&0x07e0);
}
static void progress_fields(){
  const double pos=seek_drag>=0?seek_drag:player().position();
  const int duration=player().duration;
  const auto &r=seek_slider;
  const double position=duration?std::clamp(pos*r.w/duration,0.,double(r.w)):0;
  const int end=int(position);
  const unsigned fraction=unsigned((position-end)*256);
  text_background(page_pixels,width,scratch,seek_background,seek_art[0][0],seek_art[0][1]);
  const int n=player().playing?44:1;
  const unsigned phase=player().playing?(clock_ms()*44*256/2800)%(44*256):0;
  const auto &fill=seek_art[player().playing?2:1];
  if(tinfl_decompress_mem_to_mem(scratch,2*n*r.h,text_art+fill[0],fill[1],1)==size_t(2*n*r.h)){
    for(int y=std::max(0,r.h/2-16);y<std::min(r.h,r.h/2+16);y++){
      auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(r.y+y)*width+r.x;
      auto *src=reinterpret_cast<const uint16_t*>(scratch)+y*n;
      for(int x=0;x<=end && x<r.w;x++){
        const int sample=(x+(phase>>8))%n;
        const auto pixel=interpolate_pixel(src[sample],src[(sample+1)%n],phase&255);
        dst[x]=x<end?pixel:interpolate_pixel(dst[x],pixel,fraction);
      }
    }
  }
  const Rect thumb{r.x+end-5,r.y+r.h/2-4,10,10};
  const auto &art=seek_art[3];
  if(tinfl_decompress_mem_to_mem(scratch,200,text_art+art[0],art[1],1)==200){
    for(int y=0;y<10;y++){
      auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(thumb.y+y)*width+thumb.x;
      auto *src=reinterpret_cast<const uint16_t*>(scratch)+10*y;
      for(int x=0;x<=10;x++)
        dst[x]=interpolate_pixel(x<10?src[x]:dst[x],x?src[x-1]:dst[x],fraction);
    }
  }
  playback_time(elapsed_time,int(pos));playback_time(total_time,duration);
}
static bool progress_active(){
  return current==media && player().playing && player().duration && !blanked &&
    !down && !moving && !volume_open && !queue_open && !speakers_open && !library_open;
}
static void animate_progress(){
  if(!progress_active())return;
#ifdef STUDY_CARD_PLAYER
  if(card_page_visible)return;
#endif
  static int64_t previous=0;
  const auto now=clock_ms();
  if(now-previous<16 || (scanout.active && !scanout.acquire(false)))return;
  progress_fields();
  const int top=std::min({seek_background.y,elapsed_time.rect.y,total_time.rect.y});
  const int bottom=std::max({seek_background.y+seek_background.h,
    elapsed_time.rect.y+elapsed_time.rect.h,total_time.rect.y+total_time.rect.h});
  static int shown_second=-1,labels_remaining=0;
  const int second=int(player().position());
  if(second!=shown_second){shown_second=second;labels_remaining=3;}
  // The kiosk wave occupies the centre 32 pixels of its 80-pixel touch target.
  // Paint that strip at refresh speed. Propagate changed time labels to each
  // of the three scanout buffers once per second.
  const Rect paint=labels_remaining?Rect{0,top,width,bottom-top}:
      Rect{seek_background.x,seek_slider.y+seek_slider.h/2-16,seek_background.w,32};
  if(blit(paint.x,paint.y,paint.w,paint.h,page_pixels+2*(paint.y*width+paint.x),width) && labels_remaining)
    --labels_remaining;
  previous=now;
}
static void home_player(){
  const bool cover=cover_ready && mini_art_enabled;
  const auto &art=home_strip_art[player().playing?(cover?2:1):0];
  text_background(page_pixels,width,scratch,home_strip,art[0],art[1]);
  if(player().playing){
    if(cover)draw_cover(mini_album_rect);
    label(cover?home_cover_title:home_title,player().title.empty()?"Music":player().title.c_str());
    label(cover?home_cover_artist:home_artist,player().title.empty()?"Nothing playing":player().artist.empty()?"Playing":player().artist.c_str());
  }
}
static std::string home_diagnostic_message(){
  const auto &profile=fleet.active();
  std::string notes,details;
  const char *preset_names[]={"soft","bright","soft","off","bright"};
  for(const char *preset:preset_names){
    bool seen=false;std::string differences;
    for(int i=0;i<light_count;i++){
      const int level=ha_lights.confirmed(i);
      if(!profile.members[i] || level<0)continue;
      seen=true;
      const int goal=*preset=='s'?profile.soft[i]:*preset=='b'?profile.bright[i]:0;
      if(std::abs(level-goal)<=2)continue;
      if(!differences.empty())differences+=", ";
      differences+=room_light_names[i]+std::string(" ")+std::to_string(level)+"/"+std::to_string(goal);
    }
    if(!notes.empty())notes+="   ";
    notes+=preset;notes+=!seen?" ✗ no lights seen":differences.empty()?" ✓":" ✗ "+differences;
  }
  for(int i=0;i<light_count;i++){
    const int level=ha_lights.confirmed(i);
    details+=" · "+std::string(room_light_names[i])+" "+(level<0?"unseen":std::to_string(level)+"%")+
      " want "+std::to_string(profile.soft[i])+"/"+std::to_string(profile.bright[i])+(profile.members[i]?"":" EXCLUDED");
  }
  return "touch: reports 5 points, seen "+std::to_string(observed_touches)+" · gesture "+
    (gesture_points?std::to_string(gesture_points)+"-finger":std::string("off"))+"\n"+
    notes+"\nconfig v"+std::to_string(profile.version)+details;
}
static std::string last_home_diagnostic;
#ifdef STUDY_CARD_DIAGNOSTICS
static void draw_card_home_notes(int theme,int mode,const std::string &message,uint8_t *pixels){
  const auto &box=card_diagnostics_views[theme*6+mode].badges[3];
  auto field=diag_connection;field.rect={box.x,box.y,box.w,box.h};
  field.colour=box.colour;field.baseline=box.baseline;field.spacing=box.spacing;field.align=1;
  const int bottom=height-180;
  const char *p=message.c_str();
  while(*p && field.rect.y+field.rect.h<=bottom){
    const char *first=p,*space=nullptr;int advance=0;
    while(*p && *p!='\n'){
      const char *next=p;const auto &glyph=text_glyph(field.font,next_code(next));
      if(advance+glyph.advance>box.w*64 && p!=first){if(space && space>first)p=space;break;}
      if(*p==' ')space=p;
      advance+=glyph.advance+field.spacing;p=next;
    }
    const std::string line(first,p);text_field(pixels,width,scratch,field,line.c_str(),box.y,bottom,false);
    if(*p=='\n')++p;else while(*p==' ')++p;
    field.rect.y+=box.h;
  }
  last_home_diagnostic=message;
}
#endif
static void paint_home_diagnostics(const std::string &message){
  if(!room_pixels || !page_pixels)return;
  auto field=diag_home_line;
  const int base_y=field.rect.y;
  const int bottom=std::min(home_strip.y,height);
  for(int y=base_y;y<bottom;y++){
    const int pos=2*(y*width+field.rect.x);
    memcpy(page_pixels+pos,room_pixels+pos,2*field.rect.w);
  }
  const char *p=message.c_str();
  for(int line=0;*p;line++){
    field.rect.y=base_y+(line*diag_line_height_64+32)/64;
    if(field.rect.y+field.rect.h>bottom)break;
    const char *first=p,*last_space=nullptr;
    int advance=0;
    while(*p && *p!='\n'){
      const char *next=p;const auto &g=text_glyph(field.font,next_code(next));
      if(advance+g.advance>64*field.rect.w && p!=first){if(last_space && last_space>first)p=last_space;break;}
      if(*p==' ')last_space=p;
      advance+=g.advance+field.spacing;p=next;
    }
    const auto value=std::string(first,p);
    text_field(page_pixels,width,scratch,field,value.c_str(),base_y,bottom,false);
    if(*p=='\n')++p;else while(*p==' ')++p;
  }
  last_home_diagnostic=message;
}
static void status_fields(){
#ifdef STUDY_PAGE_CRUMBS
  if(current==diagnostics_page || current==edit_page){
    const bool from_scenes=current==edit_page && depth && history[depth-1]==scenes;
    control_patch(page_pixels,page_backs[from_scenes?1:0],page_back);
  }
#endif
#ifdef USE_ESP32_HOSTED
  if(current==settings_page){
    const auto status=station.snapshot();
    label(wifi_choice,status.ssid[0]?status.ssid:"not connected");
  }
#endif
  if(current==home && diagnostics_enabled)paint_home_diagnostics(home_diagnostic_message());
  else if(current==settings_page)label(mini_choice,mini_art_enabled?"On":"Off");
  else if(current==room_menu_page){
    const time_t now=::time(nullptr);struct tm local{};localtime_r(&now,&local);
    char date[64]="–";
    if(local.tm_year>=120){
      static const char *days[]={"Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"};
      static const char *months[]={"January","February","March","April","May","June","July","August","September","October","November","December"};
      snprintf(date,sizeof(date),"%s %d %s",days[local.tm_wday],local.tm_mday,months[local.tm_mon]);
    }
    label(menu_date,date);
  }else if(current==diagnostics_page){
    label(diagnostics_enabled?diag_ha:ha_status,ha_connected()?"• connected":"• disconnected");
    std::string network_name=esphome::network::is_connected()?"Ethernet":"Disconnected";
#ifdef USE_ESP32_HOSTED
    if(!esphome::ethernet::global_eth_component->is_connected()){
      auto radio=station.snapshot();
      if(radio.ssid[0] && esphome::network::is_connected())
        network_name=std::string(radio.ssid)+" · "+std::to_string(radio.signal)+"%";
    }
#endif
    label(diagnostics_enabled?diag_net:net_status,network_name.c_str());
    label(diagnostics_enabled?diag_backlight:backlight_status,applied_brightness>=0?"• running":"• unavailable");
    const auto minutes=clock_ms()/60000;
    char uptime[32];
    if(minutes>=60)snprintf(uptime,sizeof(uptime),"%lldh %lldm",minutes/60,minutes%60);
    else snprintf(uptime,sizeof(uptime),"%lldm",minutes);
    label(diagnostics_enabled?diag_uptime:up_status,uptime);
  }
}
static void transport_fields(){
  if(library_open){paint_library();return;}
  if(speakers_open){
    text_background(page_pixels,width,scratch,{0,0,width,height},speaker_base[0],speaker_base[1]);
    label(speaker_now,transfer_status?transfer_status:speaker_labels[selected_speaker]);
    int total=0;
    for(int i=0;i<speaker_count;i++)total+=speaker_rows[i][speaker_variant(i)][2];
    speaker_max_scroll=std::max(0,total-(speaker_end-speaker_top));
    speaker_scroll=std::clamp(speaker_scroll,0,speaker_max_scroll);
    int y=speaker_top-speaker_scroll;
    for(int i=0;i<speaker_count;i++){
      const auto *r=speaker_rects[i],*art=speaker_rows[i][speaker_variant(i)];
      const int h=art[2],x=r[0],w=r[1],ax=r[2];
      auto draw=[&](const unsigned *a,int left,int sw){
        const size_t bytes=2*sw*h;
        if(tinfl_decompress_mem_to_mem(scratch,bytes,text_art+a[0],a[1],1)!=bytes)return;
        for(int row=std::max(0,speaker_top-y);row<h && y+row<speaker_end;row++)
          memcpy(page_pixels+2*((y+row)*width+left),scratch+2*row*sw,2*sw);
      };
      if(y<speaker_end && y+h>speaker_top){
        draw(art,x,w);
        if(can_transfer(i))draw(speaker_arrows[i],x+ax,w-ax);
      }
      y+=h;
    }
    return;
  }
  if(queue_open){
    const auto &list=player().playlist.empty()?player().album:player().playlist;
    const int mask=int(!player().title.empty())+2*int(!list.empty());
    text_background(page_pixels,width,scratch,queue_patches[0],queue_pages[0][0],queue_pages[0][1]);
    if(mask)text_background(page_pixels,width,scratch,queue_patches[mask],queue_pages[mask][0],queue_pages[mask][1]);
    if(mask&1){
      std::string track=player().title;
      if(!player().artist.empty())track+="  ·  "+player().artist;
      label(queue_track,track.c_str());
    }
    if(mask&2)label(mask==2?queue_playlist_2:queue_playlist_3,("Playlist: "+list).c_str());
    return;
  }
  label(song_title,player().title.empty()?"Nothing playing":player().title.c_str());
  draw_cover(album_rect);
  label(song_artist,player().title.empty()?"Browse your music library":player().artist.empty()?speaker_labels[selected_speaker]:player().artist.c_str());
  progress_fields();
  control_patch(page_pixels,shuffle_modes[player().shuffled],transport_buttons[0]);
  control_patch(page_pixels,play_modes[player().playing],transport_buttons[2]);
  control_patch(page_pixels,repeat_modes[player().repeat_mode],transport_buttons[4]);
  paint_volume();
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
enum class LightSheet {closed,more,effects,colour};
static LightSheet light_sheet=LightSheet::closed;
static int sheet_drag=-1;
static void draw_light_sheet(bool background);
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
#ifdef STUDY_CARD_EDITOR
  if(card_page_visible && (current==edit_page || current==members_page) && !moving && !down){
    if(paint_card_editor(current==members_page,page_pixels)){++revision;blit(0,0,width,height,page_pixels);}
    return;
  }
#endif
#ifdef STUDY_CARD_OVERLAYS
  if(open_card_light>=0 && !down && !moving){
    if(paint_card_detail(open_card_light,page_pixels)){++revision;blit(0,0,width,height,page_pixels);}
    return;
  }
#endif
  if(light_sheet!=LightSheet::closed && !moving && !down){draw_light_sheet(false);return;}
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
    for(auto area:{reading,slider_paint}){
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
    draw_patch(patches[value][1],slider_paint,false);
    if(update_display){
      const int x=std::min(reading.x,slider_paint.x),y=std::min(reading.y,slider_paint.y);
      const int w=std::max(reading.x+reading.w,slider_paint.x+slider_paint.w)-x;
      const int h=std::max(reading.y+reading.h,slider_paint.y+slider_paint.h)-y;
      blit(x,y,w,h,page_pixels+2*(y*width+x),width);
    }
    return;
  }
  draw_patch(patches[value][0],reading,update_display);
  draw_patch(patches[value][1],slider_paint,update_display);
}
static void animate() {
#ifdef STUDY_LIVE
#ifdef STUDY_IDENTIFY
  if(clock_ms()<identify_until){
    const int phase=int((10000-identify_until+clock_ms())/450)%2;
    if(phase==identify_phase)return;
    auto *slot=scanout.acquire(false);if(!slot)return;
    if(!phase){
      scanout.copy_pixels(slot->pixels,scratch,page_bytes);
      if(!scanout.present(slot,0,height))return;
    }else{
      ppa_blend_oper_config_t op{};
      op.in_bg.buffer=previous_pixels;op.in_bg.pic_w=width;op.in_bg.pic_h=height;
      op.in_bg.block_w=width;op.in_bg.block_h=height;op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
      op.in_fg=op.in_bg;op.in_fg.buffer=scratch;
      op.out.buffer=slot->pixels;op.out.buffer_size=page_bytes;op.out.pic_w=width;op.out.pic_h=height;
      op.out.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
      op.bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.bg_alpha_fix_val=255;
      op.fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE;op.fg_alpha_fix_val=89;
      if(ppa_do_blend(blender,&op)!=ESP_OK || !scanout.present(slot,0,1))return;
    }
    slot->page=0;slot->lamp_background=false;identify_phase=phase;return;
  }
#endif
  if(moving || progress_active())motion_loop.start();else motion_loop.stop();
  animate_progress();
#else
  if(moving)motion_loop.start();else motion_loop.stop();
#endif
#ifdef STUDY_LIVE
#ifndef STUDY_ARCHITECTURAL_ONLY
  if(diagnostic_pass>=0){diagnostic_scroll_frame();return;}
#endif
  extern void present_bell_video();
  present_bell_video();
  if(current==idle || current==doorbell)return;
#endif
  if(!moving){prepare_lamp();nav.prepare(current);return;}
  const int elapsed=clock_ms()-motion_start;
  if(playback_direction>=0){animate_cached(elapsed);return;}
  if(nav.active()){if(nav.draw(elapsed))moving=false;return;}
  await_page();
  if(elapsed>=180) {
    if(palette_motion){
      auto *slot=scanout.acquire(false);if(!slot)return;
      scanout.copy_pixels(slot->pixels,scratch,page_bytes);
      if(!scanout.present(slot,0,height))return;
      slot->page=revision;slot->lamp_background=false;palette_motion=false;
    }else blit(0,0,width,height,page_pixels);
    moving=false;
    ESP_LOGI("study","Page transition: %d frames in %lld ms",motion_frames+1,clock_ms()-motion_start);
    return;
  }
  // CSS ease-out is cubic-bezier(0,0,.58,1). Invert its time component.
  const float ease=ease_out(elapsed/180.f);
  const int offset=std::lround(travel*(1.f-ease));
  const unsigned dest_x=std::max(offset,0),src_x=std::max(-offset,0);
  auto *slot=scanout.active?scanout.acquire(false,true):nullptr;
  if(scanout.active && !slot)return;
  uint8_t *out=slot?slot->pixels:mixed_pixels;
  const auto *foreground=palette_motion?scratch:page_pixels;
  if(slot){
    const int edge=std::abs(offset),x=offset<0?width-edge:0;
    if(edge)for(int y=0;y<motion_height;y++){
      const int pos=2*(y*width+x);
      memcpy(out+pos,previous_pixels+pos,2*edge);
    }
    memcpy(out+2*width*motion_height,foreground+2*width*motion_height,2*width*(height-motion_height));
    slot->page=0;
    slot->lamp_background=false;
  }
  ppa_blend_oper_config_t op{};
  op.in_bg.buffer=previous_pixels;
  op.in_bg.pic_w=width; op.in_bg.pic_h=height;
  op.in_bg.block_w=width-std::abs(offset); op.in_bg.block_h=motion_height;
  op.in_bg.block_offset_x=dest_x; op.in_bg.blend_cm=PPA_BLEND_COLOR_MODE_RGB565;
  op.in_fg=op.in_bg; op.in_fg.buffer=foreground; op.in_fg.block_offset_x=src_x;
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
  if(slot){
#ifdef STUDY_PALETTE_PICKER
    if(!palette_motion && palette.selection()
#ifdef STUDY_CARD_ART
       && !card_page_visible
#endif
    )palette.render(reinterpret_cast<uint16_t*>(slot->pixels),0,0,width,height,false);
#endif
    if(!scanout.present(slot,0,height))return;
  }
  else blit(0,0,width,motion_height,mixed_pixels);
  ++motion_frames;
}
static void show(int dest,int shift=14) {
#ifdef STUDY_LIVE
  identify_until=0;
#endif
#ifdef STUDY_CARD_PLAYER
  theme_picker_open=false;
  if(!card_switching && selected_theme<2){
    card_travel=shift;
    const bool handled=show_card_root(dest,selected_theme,card_mode);
    card_travel=14;
    if(handled)return;
  }
#ifdef STUDY_CARD_SETTINGS
  if(!card_switching || dest!=settings_page){heap_caps_free(settings_tail);settings_tail=nullptr;settings_scroll_pixels=nullptr;}
#endif
#endif
#ifdef STUDY_CARD_ART
  card_page_visible=card_finger=false;
#ifdef STUDY_CARD_OVERLAYS
  open_card_light=-1;
#endif
  card_lights_page.cancel();
#endif
#ifdef STUDY_PALETTE_PICKER
  picker_open=false;
  if(palette.selection())palette.page(dest);
#endif
#ifdef USE_ESP32_HOSTED
  if(network_open)close_network();
#endif
  const auto request_at=clock_ms();
  await_page();
  const bool change=dest!=current;
#ifdef STUDY_LIVE
  diagnostic_pass=-1;
  light_sheet=LightSheet::closed;sheet_drag=-1;
  volume_open=false;queue_open=false;speakers_open=false;volume_drag=-1;seek_drag=-1;
  if(library_open){library.close();library_open=false;release_library_backgrounds();}
  if(change && current==doorbell)bell_client.close();
#endif
  playback_direction=-1;last_phase=-1;
  if(timeline && build_step==2*lamp_steps && levels[0]>=0 && levels[0]==prepared_level && shift==14){
    if(current==lights && dest==light0)playback_direction=0;
    if(current==light0 && dest==lights)playback_direction=1;
  }
  nav.select(current,dest,shift,request_at);
#ifdef STUDY_PALETTE_PICKER
  if(palette.selection()){nav.select(-1,-1,0,request_at);playback_direction=-1;}
#endif
  const bool transition=change && shift && blender && current!=idle && current!=doorbell && dest!=idle && dest!=doorbell;
  if(transition)std::swap(previous_pixels,page_pixels);
  palette_motion=false;
#ifdef STUDY_PALETTE_PICKER
  if(transition && scanout.active && palette.selection() && scratch && scanout.visible_pixels()){
    scanout.copy_pixels(previous_pixels,scanout.visible_pixels(),page_bytes);
    palette_motion=true;
  }
#endif
  moving=false;
  current=dest;
  ++revision;
#ifdef STUDY_CARD_PLAYER
  if(decoded_card_endpoint)return;
#endif
  auto &art=pages[current];
  auto *target=page_pixels?page_pixels:scratch;
  if(!target)return;
  const auto *cached=dest==home?room_pixels:dest==lights?lights_pixels:dest==light0?lamp_pixels:nullptr;
  int i=light_index();
  const bool parallel=transition && page_worker && playback_direction<0 && dest!=scenes && nav.can_prepare_endpoint()
#ifdef STUDY_LIVE
      && i<0 && dest!=lights && dest!=home && dest!=media && dest!=climate_page && dest!=display_page && dest!=edit_page && dest!=members_page
      && dest!=room_menu_page && dest!=settings_page && dest!=diagnostics_page
#endif
      ;
  if(parallel){
    worker_art=&art;worker_target=target;
    worker_source=dest==light0 && prepared_level!=levels[0]?nullptr:cached;
    page_pending=true;xTaskNotifyGive(page_worker);
  }else{
    // Diagnostics has a separate full-page background when badges are on.
    // Decode the selected page once. Status refreshes repaint only its fields.
#ifdef STUDY_LIVE
    if(dest==diagnostics_page && diagnostics_enabled){
      if(tinfl_decompress_mem_to_mem(target,page_bytes,text_art+diagnostic_on[0],diagnostic_on[1],1)!=page_bytes)return;
    }else
#endif
    if(cached)scanout.copy_pixels(target,cached,page_bytes);
    else if(!unpack(art,target))return;
    if(page_pixels && i>=0)paint_level(levels[i],false);
    if(page_pixels && dest==scenes)scene_fields();
#ifdef STUDY_LIVE
    if(dest==lights && (!cached || !light_list_cached))draw_light_list(target);
    if(dest==climate_page || dest==home)climate_field();
    if(dest==edit_page || dest==members_page)edit_fields();
    if(dest==display_page)display_field(screen_level());
    if(dest==media)transport_fields();
    if(dest==home)home_player();
    status_fields();
    if(i>=0)control_patch(target,detail_modes[levels[i]<0?0:levels[i]==0?1:2],detail_power_button);
#endif
  }
  if(transition) {
#ifdef STUDY_PALETTE_PICKER
    if(palette_motion){
      scanout.copy_pixels(scratch,page_pixels,page_bytes);
      palette.render(reinterpret_cast<uint16_t*>(scratch),0,0,width,height,true);
      restore_media_colours(scratch,{0,0,width,height});
    }
#endif
    if(playback_direction<0)nav.prepare_live_tiles();
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
#ifdef STUDY_CARD_FIELDS
static bool show_card_root(int dest,int theme,int mode);
#endif
static void go(int dest) {
#ifdef STUDY_LIVE
  if(dest==idle){
#ifdef STUDY_CARD_FIELDS
    card_wake=card_page_visible;
#endif
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
  if(dest==-1){
    const auto target=depth?history[--depth]:home;
#ifdef STUDY_CARD_FIELDS
    if(current==doorbell && card_ring_return){
      card_ring_return=false;
      if(show_card_root(target,card_theme,card_mode))return;
    }
#endif
    show(target);return;
  }
  if(dest==current)return;
  if(depth==24) depth=0;
  history[depth++]=current;
  show(dest);
}
#ifdef STUDY_CARD_ART
static bool card_entry(int dest){
#ifdef STUDY_CARD_PLAYER
  // Keep the displayed source frame in page_pixels while the next frame is
  // decoded into previous_pixels. Run the normal navigation cleanup and
  // preserve both themed endpoints for PPA.
  const bool animated=selected_theme<2 && card_page_visible && dest!=current && card_travel &&
                      current>=home && current<=media && dest>=home && dest<=media && blender && scanout.active;
  decoded_card_endpoint=true;
#endif
  card_switching=true;show(dest,0);card_switching=false;
#ifdef STUDY_CARD_PLAYER
  decoded_card_endpoint=false;
#endif
  std::swap(page_pixels,previous_pixels);
#ifdef STUDY_CARD_PLAYER
  return animated;
#else
  return false;
#endif
}
static bool present_card_page(bool animated){
#ifdef STUDY_CARD_PLAYER
  if(animated){
    nav.select(-1,-1,0,clock_ms());playback_direction=-1;
    motion_height=height;
    for(const auto &h:card_hits)if(h.theme==card_theme && h.page==card_page && h.action==CardAction::open_media){
      motion_height=h.y;break;
    }
    travel=card_travel;motion_frames=0;motion_start=clock_ms();moving=true;
    animate();return true;
  }
#endif
  return blit(0,0,width,height,page_pixels);
}
static bool show_card_lights(int theme,int mode){
  if(theme<0 || theme>1 || mode<0 || mode>=6 || !lcd || !previous_pixels || !page_pixels || !scratch || !card_assets_ready())return false;
  await_page();
  // Decode off-screen. A failed read must leave the current visible frame usable.
  if(!card_lights_page.open(theme,mode,previous_pixels,scratch,page_bytes,ha_lights))return false;
  // Clear overlays and release any active camera or media session through normal navigation.
  const bool animated=card_entry(lights);
  card_theme=theme;card_mode=mode;card_page=CardPage::lights;card_page_visible=true;card_finger=false;last_activity=clock_ms();++revision;
  if(present_card_page(animated))return true;
  card_switching=true;show(lights,0);card_switching=false;return false;
}
#ifdef STUDY_CARD_FIELDS
static bool paint_card_scene(int theme,int mode,CardPage page,uint8_t *pixels,bool force){
  const int mask=scene_matches();
  bool changed=false;
  if(force || mask!=card_scene_mask){
    if(!card_presets.paint(theme,mode,page==CardPage::scenes,mask,pixels,scratch,page_bytes))return false;
    changed=true;card_scene_mask=mask;
  }
  if(page==CardPage::home){
    int minute=minutes_now?minutes_now():-1;
    std::string date=card_date_now?card_date_now():"";
    if(force || minute!=card_minute || date!=card_date){
      char value[8]="--:--";
      if(minute>=0)snprintf(value,sizeof(value),"%02d:%02d",minute/60,minute%60);
      for(const auto &f:card_fields){
        if(f.theme!=theme || f.palette!=mode || f.page!=page || (f.id!=FieldId::clock && f.id!=FieldId::datestr))continue;
        if(!card_text.paint(f,f.id==FieldId::clock?value:date.c_str(),pixels,scratch,page_bytes))return false;
      }
      changed=true;card_minute=minute;card_date=std::move(date);
    }
  }
  return changed;
}
static bool show_card_scene(int theme,int mode,CardPage page){
  if((page!=CardPage::home && page!=CardPage::scenes) || !lcd || !previous_pixels || !page_pixels || !card_assets_ready())return false;
  await_page();
  if(!card_screens.read(theme,mode,page,previous_pixels,page_bytes) || !paint_card_scene(theme,mode,page,previous_pixels,true))return false;
#ifdef STUDY_CARD_DIAGNOSTICS
  if(page==CardPage::home && diagnostics_enabled)draw_card_home_notes(theme,mode,home_diagnostic_message(),previous_pixels);
#endif
#ifdef STUDY_CARD_OVERLAYS
  if(page==CardPage::home && player().playing && !paint_card_strip(theme,mode,previous_pixels))return false;
#endif
  const bool animated=card_entry(page==CardPage::home?home:scenes);
  card_theme=theme;card_mode=mode;card_page=page;card_page_visible=true;last_activity=clock_ms();++revision;
  if(present_card_page(animated))return true;
  card_switching=true;show(home,0);card_switching=false;return false;
}
#ifdef STUDY_CARD_CLIMATE
static std::string card_temperature,card_humidity;
static bool paint_card_climate(int theme,int mode,uint8_t *pixels,bool force){
  char temp[24]="~",hum[24]="~";
  if(std::isfinite(thermostat.temperature))snprintf(temp,sizeof(temp),"%.1f",double(thermostat.temperature));
  if(std::isfinite(thermostat.humidity))snprintf(hum,sizeof(hum),"%d",int(std::floor(thermostat.humidity+.5f)));
  if(!force && card_temperature==temp && card_humidity==hum)return false;
  for(const auto &f:card_fields){
    if(f.theme!=theme || f.palette!=mode || f.page!=CardPage::climate)continue;
    if(f.id!=FieldId::cTemp && f.id!=FieldId::cHum)continue;
    if(!card_text.reading(f,f.id==FieldId::cHum?hum:temp,pixels,scratch,page_bytes))return false;
  }
  card_temperature=temp;card_humidity=hum;return true;
}
#endif
static bool show_card_room_page(int theme,int mode,CardPage page){
  if(!lcd || !previous_pixels || !page_pixels || !card_assets_ready())return false;
  await_page();
  if(!card_screens.read(theme,mode,page,previous_pixels,page_bytes))return false;
  int dest=climate_page+1;
#ifdef STUDY_CARD_CLIMATE
  if(page==CardPage::climate){
    if(!paint_card_climate(theme,mode,previous_pixels,true))return false;
    dest=climate_page;
  }
#endif
  const bool animated=card_entry(dest);
  card_theme=theme;card_mode=mode;card_page=page;card_page_visible=true;
  last_activity=clock_ms();++revision;
  if(present_card_page(animated))return true;
  card_switching=true;show(dest,0);card_switching=false;return false;
}
static bool show_card_root(int dest,int theme,int mode){
  if(dest==home || dest==scenes)return show_card_scene(theme,mode,dest==home?CardPage::home:CardPage::scenes);
  if(dest==lights)return show_card_lights(theme,mode);
#ifdef STUDY_CARD_PLAYER
  if(dest==media)return show_card_player(theme,mode);
  if(dest==settings_page)return show_card_options(theme,mode,CardPage::settings);
#endif
  if(dest==climate_page+1)return show_card_room_page(theme,mode,CardPage::blinds);
#ifdef STUDY_CARD_CLIMATE
  if(dest==climate_page)return show_card_room_page(theme,mode,CardPage::climate);
#endif
  return false;
}
#ifdef STUDY_CARD_SPEAKERS
static bool paint_card_speakers(int theme,int mode,uint8_t *pixels,bool force){
  static_assert(card_speaker_count==speaker_count);
  return card_speakers.paint(theme,mode,selected_speaker,[](int i){return can_transfer(i)?4:speaker_variant(i);},
                             pixels,scratch,page_bytes,force);
}
static bool show_card_speakers(int theme,int mode){
  if(!lcd || !previous_pixels || !page_pixels || !card_assets_ready())return false;
  await_page();
  if(!card_screens.read(theme,mode,CardPage::speakers,previous_pixels,page_bytes) ||
     !paint_card_speakers(theme,mode,previous_pixels,true))return false;
  card_switching=true;show(media,0);card_switching=false;
  std::swap(page_pixels,previous_pixels);speakers_open=true;transfer_status=nullptr;
  card_page=CardPage::speakers;card_page_visible=true;card_theme=theme;card_mode=mode;
  last_activity=clock_ms();++revision;
  if(blit(0,0,width,height,page_pixels))return true;
  card_switching=true;show(media,0);card_switching=false;return false;
}
#ifdef STUDY_CARD_PLAYER
static uint16_t *card_tile=nullptr;
static size_t card_tile_bytes=0;
static bool read_player_patch(const CardPlayerPatch &p,uint8_t *target,CardArt &source=card_player_file){
  const size_t size=2u*p.w*p.h;
  if(!scratch || p.size>page_bytes || size>page_bytes || !source.read(p.offset,scratch,p.size))return false;
  return tinfl_decompress_mem_to_mem(target,size,scratch,p.size,1)==size;
}
static bool apply_player_patch(const CardPlayerPatch &p,uint8_t *frame,CardArt &source=card_player_file){
  const size_t size=2u*p.w*p.h;
  if(p.w==width && p.h==height)return read_player_patch(p,frame,source);
  if(size>card_tile_bytes){
    auto *next=static_cast<uint16_t*>(heap_caps_realloc(card_tile,size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!next)return false;
    card_tile=next;card_tile_bytes=size;
  }
  if(!read_player_patch(p,reinterpret_cast<uint8_t*>(card_tile),source))return false;
  for(int row=0;row<p.h;++row)memcpy(frame+2*((p.y+row)*width+p.x),card_tile+row*p.w,p.w*2);
  return true;
}
#ifdef STUDY_CARD_WIFI
static bool paint_card_network(){
  const auto &l=wifi_layout();
  const bool joining=wifi_selected>=0 && size_t(wifi_selected)<wifi_result.networks.size();
  const auto &sheet=wifi_sheet();
  if(!read_player_patch(joining?l.keyboard[wifi_shift]:sheet.image,page_pixels,card_wifi_file))return false;
  auto label=[&](int index,const char *value,int dy,int top=0,int bottom=height){
    auto f=l.fields[index];f.y+=dy;
    return card_wifi_text.write(f,value,page_pixels,scratch,page_bytes,top,bottom);
  };
  const int shift=sheet.top-l.top;
  if(!joining && wifi_scroll){
    const int body=height-sheet.top;
    const int distance=std::min(wifi_scroll,body);
    const size_t stride=width*2;
    uint8_t *start=page_pixels+sheet.top*stride;
    // The CM5 scrolls the title and connection status with the list. The blank
    // bottom padding supplies the sheet colour behind newly revealed rows.
    memcpy(scratch,page_pixels+(height-1)*stride,stride);
    memmove(start,start+distance*stride,(body-distance)*stride);
    for(int y=height-distance;y<height;++y)memcpy(page_pixels+y*stride,scratch,stride);
  }
  std::string connection="not connected";
  if(wifi_result.ssid[0])connection=std::string(wifi_result.ssid)+" · "+std::to_string(wifi_result.signal)+"%";
  if(!label(joining?3:0,connection.c_str(),joining?0:shift-wifi_scroll,joining?0:sheet.top))return false;
  if(joining){
    const auto &net=wifi_result.networks[wifi_selected];
    const char *msg=wifi_result.state==Wifi::State::joining?"Connecting…":wifi_result.state==Wifi::State::failed?"Failed":net.secure?"":"open network";
    return label(4,net.ssid,0) && label(5,msg,0) && label(6,wifi_password_preview().c_str(),0);
  }
  auto r=wifi_first_row();
  if(wifi_result.networks.empty()){
    const char *message=wifi_result.state==Wifi::State::scanning?"Scanning…":wifi_result.state==Wifi::State::failed?"Wi-Fi unavailable":"No networks found";
#ifdef STUDY_CARD_MOTION_GEOMETRY
    const auto &n=wifi_empty_note[selected_theme];
    // The empty note has height even when zero network rows are present.
    int dy=n[5]-sheet.top;
    if(dy<0){
      const int line=2*width;
      memmove(page_pixels+line*n[5],page_pixels+line*sheet.top,line*(height-sheet.top));
      for(int y=height+dy;y<height;++y)memcpy(page_pixels+line*y,page_pixels+line*(height+dy-1),line);
    }
    auto f=l.fields[0];f.x=n[0];f.y=n[1];f.w=n[2];f.h=n[3];f.baseline=n[4];f.align=1;
    return card_wifi_text.write(f,message,page_pixels,scratch,page_bytes,0,height);
#else
    return label(0,message,r.y-l.fields[0].y);
#endif
  }
  for(size_t i=0;i<wifi_result.networks.size();++i){
    const int y=r.y+int(i)*l.step-wifi_scroll;
    if(y+r.h<=sheet.top)continue;
    if(y>=height)break;
    const auto &net=wifi_result.networks[i];
    const auto &patch=l.rows[2*int(net.secure)+(!strcmp(net.ssid,wifi_result.ssid))];
    const size_t size=2u*patch.w*patch.h;
    if(size>card_tile_bytes){
      auto *buf=static_cast<uint16_t*>(heap_caps_realloc(card_tile,size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!buf)return false;
      card_tile=buf;card_tile_bytes=size;
    }
    if(!read_player_patch(patch,reinterpret_cast<uint8_t*>(card_tile),card_wifi_file))return false;
    for(int j=std::max(0,sheet.top-y);j<r.h && y+j<height;++j)
      memcpy(page_pixels+2*((y+j)*width+r.x),card_tile+j*r.w,2*r.w);
    const char *bars=net.signal>=75?"▂▄▆█":net.signal>=50?"▂▄▆":net.signal>=25?"▂▄":"▂";
    char signal[32];snprintf(signal,sizeof(signal),"%s %u%%",bars,unsigned(net.signal));
    if(!label(1,net.ssid,y-l.row.y,sheet.top) || !label(2,signal,y-l.row.y,sheet.top))return false;
  }
  return true;
}
#endif
struct CardProgress {
  uint16_t *data=nullptr;
  size_t capacity=0;
  int bank=-1;
  bool draw(int theme,int mode,uint8_t *frame){
    const int index=theme*6+mode;
    const auto *art=card_transport[index]+7;
    const auto &bar=seek_slider;
    size_t offset[4],size=0;
    for(int i=0;i<4;++i){offset[i]=size;size+=art[i].w*art[i].h;}
    if(size>capacity){
      auto *next=static_cast<uint16_t*>(heap_caps_realloc(data,2*size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!next)return false;
      data=next;capacity=size;bank=-1;
    }
    if(bank!=index){
      bank=-1;
      for(int i=0;i<4;++i)if(!read_player_patch(art[i],reinterpret_cast<uint8_t*>(data+offset[i])))return false;
      bank=index;
    }
    auto *pixels=reinterpret_cast<uint16_t*>(frame);
    const int pos=seek_drag>=0?seek_drag:int(std::lround(player().position()));
    const int end=player().duration?std::clamp(int(std::lround(double(pos)*bar.w/player().duration)),0,bar.w):0;
    const int pattern=player().playing?2:1;
    const int phase=player().playing?int(clock_ms()*44/2800%44):0;
    for(int row=0;row<art[0].h;++row){
      auto *line=pixels+(art[0].y+row)*width;
      memcpy(line+art[0].x,data+offset[0]+row*art[0].w,2*art[0].w);
      auto *tile=data+offset[pattern]+row*art[pattern].w;
      for(int x=0;x<end;++x)line[bar.x+x]=tile[(x+phase)%art[pattern].w];
    }
    for(int row=0;row<art[3].h;++row)
      memcpy(pixels+(art[3].y+row)*width+bar.x+end-5,data+offset[3]+row*art[3].w,2*art[3].w);
    return true;
  }
};
static CardProgress card_progress;
static bool paint_card_player(int theme,int mode,uint8_t *frame,bool progress_only){
  const int pos=seek_drag>=0?seek_drag:int(std::lround(player().position()));
  char elapsed[24],duration[24],volume[12];
  snprintf(elapsed,sizeof(elapsed),"%d:%02d",pos/60,pos%60);
  snprintf(duration,sizeof(duration),"%d:%02d",player().duration/60,player().duration%60);
  snprintf(volume,sizeof(volume),"%d%%",std::max(0,player().volume));
  for(const auto &f:card_fields){
    if(f.theme!=theme || f.palette!=mode || f.page!=CardPage::media)continue;
    const char *v=nullptr;
    if(f.id==FieldId::mElapsed)v=elapsed;
    else if(f.id==FieldId::mDur)v=duration;
    else if(progress_only)continue;
    else if(f.id==FieldId::mTitle)v=player().title.empty()?"Nothing playing":player().title.c_str();
    else if(f.id==FieldId::mArtist)v=player().title.empty()?"Browse your music library":player().artist.empty()?speaker_labels[selected_speaker]:player().artist.c_str();
    else if(f.id==FieldId::mpVolumeValue)v=volume;
    if(v && !card_text.paint(f,v,frame,scratch,page_bytes))return false;
  }
  if(!card_progress.draw(theme,mode,frame))return false;
  if(progress_only)return true;
  const auto *art=card_transport[theme*6+mode];
  for(int i:{int(player().shuffled),2+int(player().playing),4+player().repeat_mode})
    if(!apply_player_patch(art[i],frame))return false;
  if(cover_ready && cover_pixels)for(int y=0;y<album_rect.h;++y)
    memcpy(frame+2*((album_rect.y+y)*width+album_rect.x),cover_pixels+y*album_rect.w,2*album_rect.w);
  return true;
}
static bool present_card_view(int theme,int mode,CardPage page,int dest){
  const bool animated=card_entry(dest);
  card_theme=theme;card_mode=mode;card_page=page;card_page_visible=true;
  last_activity=clock_ms();++revision;
  return present_card_page(animated);
}
static bool show_card_player(int theme,int mode){
  if(!lcd || !previous_pixels || !page_pixels || !card_assets_ready())return false;
  await_page();
  if(!card_screens.read(theme,mode,CardPage::media,previous_pixels,page_bytes) ||
     !paint_card_player(theme,mode,previous_pixels,false))return false;
  return present_card_view(theme,mode,CardPage::media,media);
}
#ifdef STUDY_CARD_OVERLAYS
static bool overlay_patch(unsigned table,unsigned index,uint8_t *pixels){
  CardPlayerPatch p{};
  static_assert(sizeof(p)==16);
  return card_overlay_file.read(table+index*sizeof(p),&p,sizeof(p)) &&
         apply_player_patch(p,pixels,card_overlay_file);
}
static const CardMusicOverlay &music_overlay(){return card_music_views[card_theme*6+card_mode];}
#ifdef STUDY_CARD_MOTION_GEOMETRY
static void paint_equalizer(uint8_t *frame,int theme,int mode,int64_t now){
  const auto &bars=eq_bars[theme][mini_art_enabled];
  auto *pixels=reinterpret_cast<uint16_t*>(frame);
  constexpr int periods[]={900,620,1050,780};
  for(int i=0;i<4;++i){
    const auto &r=bars[i];
    const double phase=double(now%(2*periods[i]))/periods[i];
    const double t=phase>1?2-phase:phase;
    const double eased=t*t*(3-2*t);
    const int span=std::lround(r.h*(.22+.78*eased));
    for(int y=0;y<r.h;++y){
      auto *row=pixels+(r.y+y)*width+r.x;
      // The two pixels beside the bar belong to the same strip background.
      for(int x=0;x<r.w;++x){
        const bool corner=(y==r.h-span || y==r.h-1) && (x==0 || x==r.w-1);
        row[x]=y>=r.h-span && !corner?eq_accent[theme][mode]:row[x<r.w/2?-1:r.w];
      }
    }
  }
}
#endif
static bool overlay_label(const LibraryField &f,const char *value,uint8_t *pixels){
  return card_overlay_text.write(f,value,pixels,scratch,page_bytes,0,height);
}
static bool paint_card_strip(int theme,int mode,uint8_t *pixels){
  const auto &s=card_music_views[theme*6+mode].strip[mini_art_enabled];
  if(!apply_player_patch(s.tile,pixels,card_overlay_file) ||
     !overlay_label(s.text[0],player().title.empty()?"Nothing playing":player().title.c_str(),pixels) ||
     !overlay_label(s.text[1],player().artist.c_str(),pixels))return false;
  if(cover_ready && cover_pixels && s.cover.w){
    const auto &r=s.cover;
    for(int y=0;y<r.h;++y){
      auto *out=reinterpret_cast<uint16_t*>(pixels)+(r.y+y)*width+r.x;
      const auto *src=cover_pixels+(y*album_rect.h/r.h)*album_rect.w;
      for(int x=0;x<r.w;++x)out[x]=src[x*album_rect.w/r.w];
    }
  }
  const auto &bar=s.progress;
  const int amount=player().duration?std::clamp(int(std::lround(bar.w*player().position()/player().duration)),0,bar.w):0;
  for(int y=0;y<bar.h;++y)std::fill_n(reinterpret_cast<uint16_t*>(pixels)+(bar.y+y)*width+bar.x,amount,
#ifdef STUDY_CARD_MOTION_GEOMETRY
    eq_accent[theme][mode]);
  paint_equalizer(pixels,theme,mode,clock_ms());
#else
    uint16_t(s.text[0].colour));
#endif
  return true;
}
static int card_queue_state(){return int(!player().title.empty())+2*int(!player().playlist.empty() || !player().album.empty());}
// Chromium draws the sheet over a black scrim at 62% opacity. Preserve live
// artwork, transport and light levels behind it at the panel's RGB565 depth.
static void card_scrim(const uint8_t *live,uint8_t *sheet,int top){
  static uint8_t shade[64];
  if(!shade[63])for(int i=0;i<64;++i)shade[i]=(38*i+50)/100;
  const auto *source=reinterpret_cast<const uint16_t*>(live);
  auto *out=reinterpret_cast<uint16_t*>(sheet);
  for(int n=0;n<top*width;++n){
    const uint16_t rgb=source[n];
    out[n]=(shade[rgb>>11]<<11)|(shade[(rgb>>5)&63]<<5)|shade[rgb&31];
  }
}
static bool paint_card_popup(bool volume,uint8_t *pixels){
  const auto &v=music_overlay();
  if(volume){
    int value=volume_drag>=0?volume_drag:std::clamp(player().volume,0,100);
    const std::string text=std::to_string(value)+"%";
    return paint_card_player(card_theme,card_mode,pixels,false) &&
           overlay_patch(v.volume,value,pixels) && overlay_label(v.level,text.c_str(),pixels);
  }
  const int state=card_queue_state();const auto &q=v.queue[state];
  if(!read_player_patch(q.base,pixels,card_overlay_file))return false;
  uint8_t *behind=pixels==page_pixels?previous_pixels:page_pixels;
  if(!card_screens.read(card_theme,card_mode,CardPage::media,behind,page_bytes) ||
     !paint_card_player(card_theme,card_mode,behind,false))return false;
  card_scrim(behind,pixels,q.top);
  int row=0;
  if(state&1){
    auto title=player().title;
    if(!player().artist.empty())title+="  ·  "+player().artist;
    if(!overlay_label(q.text[row++],title.c_str(),pixels))return false;
  }
  if(state&2){
    auto title="Playlist: "+(player().playlist.empty()?player().album:player().playlist);
    if(!overlay_label(q.text[row],title.c_str(),pixels))return false;
  }
  return true;
}
static bool open_card_popup(bool volume){
  if(volume && !card_screens.read(card_theme,card_mode,CardPage::media,previous_pixels,page_bytes))return false;
  if(!paint_card_popup(volume,previous_pixels))return false;
  if(!present_card_view(card_theme,card_mode,volume?CardPage::volume:CardPage::queue,media))return false;
  volume_open=volume;queue_open=!volume;return true;
}
static const CardDetail &detail_layout(int i){return card_detail_views[(card_theme*6+card_mode)*light_count+i];}
static bool paint_card_detail(int i,uint8_t *pixels){
  const auto &l=detail_layout(i);
  if(!apply_player_patch(l.sheet,pixels,card_overlay_file))return false;
  const auto &d=ha_lights.detail(i);
  const bool pending=edit_slot==i+2 && edit_waiting;
  const int check=(fleet.active().members[i]!=pending)+2*(edit_slot==i+2 && edit_feedback==2);
  if(!apply_player_patch(l.check[check],pixels,card_overlay_file))return false;
  constexpr int hues[]={0,20,40,60,120,180,200,220,260,290,320,340};
  for(int n=0;n<l.total;++n){
    bool active=false;
    if(n<l.colours && n<int(std::size(hues)))active=d.hue>=0 && std::abs(d.hue-hues[n])<10;
    else if(n>=l.colours && effect_starts[i]+n-l.colours<effect_starts[i+1])
      active=d.effect==effect_names[effect_starts[i]+n-l.colours];
    if(!overlay_patch(l.offset,2*n+active,pixels))return false;
  }
  if(l.warmth.w){
    const auto &r=l.warmth;
    const int p=sheet_drag>=0?sheet_drag:d.kelvin>=0 && d.maximum>d.minimum?
      std::clamp(int(std::lround(100.*(d.kelvin-d.minimum)/(d.maximum-d.minimum))),0,100):50;
    const int k=sheet_drag>=0?std::lround(d.minimum+(d.maximum-d.minimum)*p/100.):d.kelvin;
    const std::string label=k<0?"—K":std::to_string(k)+"K";
    if(!overlay_label(l.text,label.c_str(),pixels))return false;
    if(!overlay_patch(l.knob,p,pixels))return false;
  }
  return true;
}
static bool open_card_detail(int i){
  const auto page=static_cast<CardPage>(int(CardPage::detail0)+i);
  if(!card_screens.read(card_theme,card_mode,page,previous_pixels,page_bytes) || !paint_card_detail(i,previous_pixels))return false;
  card_scrim(page_pixels,previous_pixels,detail_layout(i).top);
  if(!present_card_view(card_theme,card_mode,page,lights))return false;
  open_card_light=i;return true;
}
#ifdef STUDY_CARD_EDITOR
static const EditView &card_editor_view(){return card_edit_views[card_theme*6+card_mode];}
static bool paint_card_editor(bool members,uint8_t *pixels){
  const auto &v=card_editor_view();
  if(!read_player_patch(members?v.members:v.edit,pixels,card_editor_file))return false;
  for(int i=0;i<(members?light_count:2);++i){
    const auto &button=members?v.lights[i]:v.saves[i];
    bool pending=edit_slot==i+2 && edit_waiting;
    int mode=members?(fleet.active().members[i]!=pending)+2*(edit_slot==i+2 && edit_feedback==2):edit_slot==i?edit_feedback:0;
    CardPlayerPatch p{};
    if(!card_editor_file.read(button.table+mode*sizeof(p),&p,sizeof(p)) || !apply_player_patch(p,pixels,card_editor_file))return false;
  }
  return true;
}
static bool open_card_editor(bool members){
  if(!paint_card_editor(members,previous_pixels))return false;
  return present_card_view(card_theme,card_mode,CardPage::scenes,members?members_page:edit_page);
}
#endif
#endif
#ifdef STUDY_CARD_BACKLIGHT
static bool paint_settings_level(int theme,int mode,int value,uint8_t *frame){
  const auto &slider=card_setting_sliders[theme*6+mode];
  uint32_t refs[4];
  if(!card_settings_file.read(slider.table+sizeof(refs)*value,refs,sizeof(refs)))return false;
  for(int i=0;i<2;++i){
    const auto &r=slider.patches[i];
    if(!apply_player_patch({uint16_t(r.x),uint16_t(r.y),uint16_t(r.w),uint16_t(r.h),refs[i*2],refs[i*2+1]},frame,card_settings_file))return false;
  }
  shown_brightness=value;return true;
}
static bool update_settings_level(int value){
  if(!settings_scroll_pixels || !paint_settings_level(card_theme,card_mode,value,settings_scroll_pixels))return false;
  const auto &view=card_settings_views[(card_theme*6+card_mode)*2+int(diagnostics_enabled)];
  const auto &slider=card_setting_sliders[card_theme*6+card_mode];
  const int top=std::max(0,slider.patches[1].y-settings_offset);
  const int bottom=std::min(view.height,slider.patches[0].y+slider.patches[0].h-settings_offset);
  if(bottom<=top)return true;
  memcpy(page_pixels+2*width*top,settings_scroll_pixels+2*width*(top+settings_offset),2*width*(bottom-top));
  ++revision;return blit(0,top,width,bottom-top,page_pixels+2*width*top,width);
}
#endif
#ifdef STUDY_CARD_SETTINGS
static void copy_settings_window(uint8_t *out,int h,int offset){
  const size_t stride=2*width;
  const int first=std::max(0,h-offset);
  memcpy(out,settings_scroll_pixels+stride*offset,stride*first);
  if(offset)memcpy(out+stride*first,settings_tail,stride*offset);
}
#endif
#ifdef STUDY_CARD_DIAGNOSTICS
static void settings_live_text(int theme,int mode,uint8_t *pixels,int extent,int origin=0){
  const auto &labels=card_diagnostics_views[theme*6+mode].settings[int(diagnostics_enabled)];
  std::string network=esphome::network::is_connected()?"Ethernet":"not connected",wifi="not connected";
#ifdef USE_ESP32_HOSTED
  const auto status=station.snapshot();
  if(status.ssid[0]){
    wifi=status.ssid;
    if(!esphome::ethernet::global_eth_component->is_connected())network=wifi+" · "+std::to_string(status.signal)+"%";
  }
#endif
  const int minutes=int(clock_ms()/60000);
  std::string uptime=minutes>=60?std::to_string(minutes/60)+"h "+std::to_string(minutes%60)+"m":std::to_string(minutes)+"m";
  const char *values[]={uptime.c_str(),"ESP32-P4 · DSI",mini_art_enabled?"On":"Off",wifi.c_str(),
                        diagnostics_enabled?"On":"Off",ha_connected()?"• connected":"• disconnected",network.c_str()};
  for(unsigned i=0;i<std::size(values);++i){
    const auto &s=labels[i];auto r=s.label;r.y-=origin;
    if(!s.size || r.y<0 || r.y+r.h>extent)continue;
    const size_t bytes=2*r.w*r.h;
    if(tinfl_decompress_mem_to_mem(scratch,bytes,diag_settings_art+s.offset,s.size,1)!=bytes)continue;
    for(int y=0;y<r.h;++y)memcpy(pixels+2*((r.y+y)*width+r.x),scratch+2*y*r.w,2*r.w);
    for(const auto &f:card_fields){
      auto id=i>=2 && i<=4?FieldId::wifiV:FieldId::sUp;
      if(f.theme!=theme || f.palette!=mode || f.page!=CardPage::settings || f.id!=id)continue;
      auto label=f;
      label.x=r.x;label.y=r.y;label.w=r.w;label.h=r.h;label.baseline=r.baseline;
      label.spacing=r.spacing;label.colour=r.colour;label.align=2;
      card_text.write(label,values[i],pixels,scratch,page_bytes,0,extent);break;
    }
  }
}
#endif
static bool show_card_options(int theme,int mode,CardPage page){
  if(!lcd || !previous_pixels || !page_pixels || !card_assets_ready())return false;
  await_page();
  bool loaded=false;
#ifdef STUDY_CARD_SETTINGS
  const auto &view=card_settings_views[(theme*6+mode)*2+int(diagnostics_enabled)];
  if(page!=CardPage::settings){heap_caps_free(settings_tail);settings_tail=nullptr;settings_scroll_pixels=nullptr;}
  if(page==CardPage::settings){
    if(!read_player_patch({0,0,width,height,view.top,view.top_bytes},previous_pixels,card_settings_file))return false;
    loaded=true;
  }
#endif
  if(!loaded && !card_screens.read(theme,mode,page,previous_pixels,page_bytes))return false;
  if(page==CardPage::settings){
#ifndef STUDY_CARD_DIAGNOSTICS
    std::string network=esphome::network::is_connected()?"Ethernet":"not connected";
    std::string wifi="not connected";
#ifdef USE_ESP32_HOSTED
    const auto status=station.snapshot();
    if(status.ssid[0]){
      wifi=status.ssid;
      if(!esphome::ethernet::global_eth_component->is_connected())network=wifi+" · "+std::to_string(status.signal)+"%";
    }
#endif
    const auto minutes=clock_ms()/60000;
    const auto uptime=minutes>=60?std::to_string(minutes/60)+"h "+std::to_string(minutes%60)+"m":std::to_string(minutes)+"m";
    for(const auto &f:card_fields){
      if(f.page!=page || f.theme!=theme || f.palette!=mode)continue;
      const char *value=f.id==FieldId::stHA?(ha_connected()?"• connected":"• disconnected"):
                        f.id==FieldId::sUp?uptime.c_str():f.id==FieldId::diagV?(diagnostics_enabled?"On":"Off"):
                        f.id==FieldId::stNet?network.c_str():f.id==FieldId::wifiV?wifi.c_str():nullptr;
      if(value && !card_text.paint(f,value,previous_pixels,scratch,page_bytes))return false;
    }
#endif
#ifdef STUDY_CARD_SETTINGS
    const auto line=2*width;
#ifdef STUDY_CARD_BACKLIGHT
    if(!paint_settings_level(theme,mode,screen_level(),previous_pixels))return false;
#endif
    // Settings has no page transition. Its outgoing buffer is available for
    // the fixed upper part while the display controller owns the visible frame.
    auto *tail=static_cast<uint8_t*>(heap_caps_realloc(settings_tail,line*view.scroll,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!tail)return false;
    settings_tail=tail;
    settings_scroll_pixels=page_pixels;
    memcpy(settings_scroll_pixels,previous_pixels,line*view.height);
    if(!read_player_patch({0,0,width,uint16_t(view.scroll),view.tail,view.tail_bytes},tail,card_settings_file))return false;
#ifdef STUDY_CARD_DIAGNOSTICS
    settings_live_text(theme,mode,settings_scroll_pixels,view.height);
    settings_live_text(theme,mode,tail,view.scroll,view.height);
#endif
    settings_offset=card_page_visible && card_page==CardPage::settings?std::min(settings_offset,view.scroll):0;
    copy_settings_window(previous_pixels,view.height,settings_offset);
#endif
  }
  return present_card_view(theme,mode,page,settings_page);
}
#ifdef STUDY_CARD_LIBRARY
static const LibraryLayout &library_layout(){
  return card_library_layouts[(card_theme*6+card_mode)*2+(library_steps[library_mode][0]==1)];
}
static bool paint_card_library(bool benchmark=false){
  const auto &l=library_layout();
  const int index=&l-card_library_layouts;
  if(index!=card_library_index){
    release_library_backgrounds();
    card_library_background=page_buffer();
    if(card_library_background && !read_player_patch(l.base,card_library_background,card_library_file))return false;
    for(int i=0;i<2;++i){
      auto &tile=library_background[i];
      tile=static_cast<uint8_t*>(heap_caps_malloc(2*l.tiles[i].w*l.tiles[i].h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!tile || !read_player_patch(l.tiles[i],tile,card_library_file))return false;
    }
    card_library_index=index;
  }
  if(card_library_background)memcpy(page_pixels,card_library_background,page_bytes);
  else if(!read_player_patch(l.base,page_pixels,card_library_file))return false;
  const auto &v=l.viewport;
  const int end=std::min(height,v.y+v.h);
  std::string crumb="Library";
  for(const auto &f:library.folders)crumb+="  ›  "+f.title;
  auto write=[&](auto f,const std::string &s,int dx,int dy,int top,int bottom){
    f.x+=dx;f.y+=dy;return card_library_text.write(f,s.c_str(),page_pixels,scratch,page_bytes,top,bottom);
  };
  if(benchmark)crumb=diagnostic_pass==6?"Close and reopen to browse again":
      std::string(diagnostic_cases[diagnostic_pass])+"  ("+std::to_string(diagnostic_pass+1)+" of 6)";
  if(!write(l.fields[0],benchmark?"Scroll test":library.folders.empty()?"Library":library.folders.back().title,0,0,0,height) ||
     !write(l.fields[1],crumb,0,0,0,height))return false;
  if(benchmark){
    const auto &tile=l.tiles[1];
    for(int n=0;n<(diagnostic_pass==6?6:200);++n){
      int x=v.x+(n%l.cols)*l.spacing,y=v.y+(n/l.cols)*l.step-diagnostic_offset;
      if(y>=end && diagnostic_pass!=2)break;
      if(y>=end || y+tile.h<=v.y)continue;
      if(diagnostic_pass==1 && !read_player_patch(tile,library_background[1],card_library_file))return false;
      const auto &icon=l.icons[1];
      for(int j=std::max(0,v.y-y);j<tile.h && y+j<end;++j){
        auto *line=reinterpret_cast<uint16_t*>(page_pixels)+(y+j)*width+x;
        const auto *src=reinterpret_cast<uint16_t*>(library_background[1])+j*tile.w;
        if(diagnostic_pass==5)std::fill_n(line,tile.w,uint16_t(0x18e4));
        else memcpy(line,src,tile.w*2);
        if(diagnostic_pass==6 || (j>=icon.y-tile.y && j<icon.y-tile.y+icon.h)){
          int left=icon.x-tile.x;
          std::fill_n(line+left,icon.w,src[std::min(tile.w-1,left+icon.w+1)]);
        }
      }
      if(diagnostic_pass==4)continue;
      std::string title=diagnostic_pass==6?diagnostic_cases[n]:"Row "+std::to_string(n);
      std::string detail="test";
      if(diagnostic_pass==6){
        int d=std::lround(100.*(diagnostic_rates[n]-diagnostic_rates[0])/std::max(1,diagnostic_rates[0]));
        detail=std::to_string(diagnostic_rates[n])+" fps · "+(n?(d>=0?"+":"")+std::to_string(d)+
          (std::abs(d)<25?"%  (within noise)":"%  ← this one matters"):"baseline");
      }
      if(!write(l.fields[4],title,x-tile.x,y-tile.y,v.y,end) ||
         !write(l.fields[5],detail,x-tile.x,y-tile.y,v.y,end))return false;
    }
    return true;
  }
  if(*library.message)return write(l.fields[1],library.message,0,v.y-l.fields[1].y+20,v.y,end);
  for(size_t i=0;i<library.items.size();++i){
    const auto &item=library.items[i];
    const int variant=item.expand?0:1;
    const auto &tile=l.tiles[variant];
    const size_t n=library.first+i;
    const int x=v.x+int(n%l.cols)*l.spacing,y=v.y+int(n/l.cols)*l.step-library_scroll;
    if(y>=end)break;
    if(y+tile.h<=v.y)continue;
    const int dx=x-tile.x,dy=y-tile.y;
    for(int row=std::max(0,v.y-y);row<tile.h && y+row<end;++row)
      memcpy(page_pixels+2*((y+row)*width+x),library_background[variant]+2*row*tile.w,2*tile.w);
    const auto &icon=l.icons[variant];
    bool thumbnail=false;
    if(!item.thumbnail.empty())for(auto &t:thumbnails)if(t.ready && t.url==item.thumbnail){
      for(int row=std::max(0,v.y-icon.y-dy);row<icon.h && icon.y+dy+row<end;++row){
        auto *out=reinterpret_cast<uint16_t*>(page_pixels)+(icon.y+dy+row)*width+icon.x+dx;
        for(int col=0;col<icon.w;++col)out[col]=t.pixels[(row*thumbnail_side/icon.h)*thumbnail_side+col*thumbnail_side/icon.w];
      }
      t.used=++thumbnail_stamp;thumbnail=true;break;
    }
    if(!thumbnail && item.expand && item.category!="directory"){
      const auto &note=l.icons[1];const auto &other=l.tiles[1];
      for(int row=std::max(0,v.y-icon.y-dy);row<std::min(icon.h,note.h) && icon.y+dy+row<end;++row)
        memcpy(page_pixels+2*((icon.y+dy+row)*width+icon.x+dx),
               library_background[1]+2*((note.y-other.y+row)*other.w+note.x-other.x),2*std::min(icon.w,note.w));
    }
    if(!write(l.fields[2+variant*2],item.title,dx,dy,v.y,end) ||
       !write(l.fields[3+variant*2],item.category,dx,dy,v.y,end))return false;
  }
  return true;
}
static bool card_diagnostic_frame(){
  if(!diagnostic_frames)diagnostic_start=clock_ms();
  if(!paint_card_library(true)){diagnostic_pass=-1;return false;}
  ++revision;
  if(blit(0,0,width,height,page_pixels))++diagnostic_frames;
  const auto &l=library_layout();
  diagnostic_offset=(diagnostic_offset+7)%std::max(1,((200+l.cols-1)/l.cols)*l.step-l.viewport.h);
  auto elapsed=clock_ms()-diagnostic_start;
  if(elapsed<2500)return true;
  diagnostic_rates[diagnostic_pass]=std::lround(diagnostic_frames*1000./elapsed);
  ESP_LOGI("study","Scroll test %s %d fps",diagnostic_cases[diagnostic_pass],diagnostic_rates[diagnostic_pass]);
  ++diagnostic_pass;diagnostic_frames=0;
  if(diagnostic_pass==6){
    diagnostic_offset=0;
    if(!paint_card_library(true))return false;
    ++revision;return blit(0,0,width,height,page_pixels);
  }
  return true;
}
static bool open_card_library(){
  if(!card_assets_ready())return false;
  library_open=true;library_scroll=0;library.open(speaker_ids[selected_speaker]);
  card_page=library_steps[library_mode][0]==1?CardPage::library_alt:CardPage::library;
  if(paint_card_library()){++revision;return blit(0,0,width,height,page_pixels);}
  show_card_player(card_theme,card_mode);return false;
}
#endif
static bool open_theme_picker(){
  if(!card_assets_ready() || !apply_player_patch(card_theme_choices[palette.selection()],previous_pixels))return false;
  std::swap(previous_pixels,page_pixels);theme_picker_open=true;card_switching=false;
  card_page_visible=true;++revision;return blit(0,0,width,height,page_pixels);
}
static bool select_theme(int theme){
  if(theme<0 || theme>2 || !card_assets_ready())return false;
  if(theme==2){
    if(!remember_screen("theme",2,fleet.active().screen.theme))return false;
    selected_theme=2;depth=0;report_screen();show(display_page,0);
    if(!palette.selection())nav.restore_chunks();
    return open_theme_picker();
  }
  // These layouts draw from their CM5 endpoints. Release the Architectural
  // decoder's optional run cache for the Settings sheet and library tiles.
  nav.use_palette_memory();
  if(!show_card_options(theme,palette.selection(),CardPage::theme) || !remember_screen("theme",theme,fleet.active().screen.theme)){
    if(selected_theme==2 && !palette.selection())nav.restore_chunks();
    return false;
  }
  depth=0;selected_theme=theme;report_screen();return true;
}

#endif
#endif
#endif
#endif
#ifdef STUDY_SCREEN_OPTIONS
static void apply_screen_profile(const ScreenChoices &screen,bool render){
  const int old_theme=selected_theme,old_palette=palette.selection(),old_library=library_mode;
  const bool old_diagnostics=diagnostics_enabled,old_mini=mini_art_enabled;
  // A reply to our previous tap can arrive after another tap. Move the local
  // baseline forward only for values acknowledged by that signed reply.
  const uint8_t base=(library_steps[0][0]>1)==screen.tiles?0:1;
  if(render && fleet.acknowledged_display()){
    if(screen.theme==reported_screen.theme && selected_theme!=screen.theme)remember_screen("theme",selected_theme,screen.theme);
    if(screen.palette==reported_screen.palette && card_mode!=screen.palette)remember_screen("palette",card_mode,screen.palette);
    if(screen.diagnostics==reported_screen.diagnostics && diagnostics_enabled!=screen.diagnostics)remember_screen("diag",diagnostics_enabled,screen.diagnostics);
    if(screen.tiles==reported_screen.tiles && library_mode!=base)remember_screen("libview",library_mode,base);
    if(screen.mini_art==reported_screen.mini_art && mini_art_enabled!=screen.mini_art)remember_screen("mini",mini_art_enabled,screen.mini_art);
  }
#ifndef STUDY_ARCHITECTURAL_ONLY
  selected_theme=local_screen("theme",screen.theme,2);
#endif
  card_mode=local_screen("palette",screen.palette,5);
  diagnostics_enabled=local_screen("diag",screen.diagnostics,1);
  mini_art_enabled=local_screen("mini",screen.mini_art,1);
  library_mode=local_screen("libview",base,1);
  if(!render || !palette.available())return;
  if(selected_theme<2)nav.use_palette_memory();
  if(old_theme==selected_theme && old_palette==card_mode &&
     old_library==library_mode && old_diagnostics==diagnostics_enabled && old_mini==mini_art_enabled)return;
  if(!palette.selection() && card_mode)nav.use_palette_memory();
  if(!palette.choose(card_mode,scratch))return;
  if(!card_mode && selected_theme==2)nav.restore_chunks();
  if(current!=doorbell && current!=idle){depth=0;show(home,0);}
}
#endif
static void begin(Display *display) {
  lcd=display;
#ifdef STUDY_LIVE
  const auto *part=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,static_cast<esp_partition_subtype_t>(0x40),"motion");
  static esp_partition_mmap_handle_t volume_mapping;
  const void *mapped=nullptr;unsigned char digest[32];
#ifdef STUDY_PALETTE_PICKER
  if(!palette.begin(part))ESP_LOGW("study","Palette bank unavailable");
#endif
  if(part && esp_partition_mmap(part,volume_offset,volume_size,ESP_PARTITION_MMAP_DATA,&mapped,&volume_mapping)==ESP_OK &&
     !mbedtls_sha256(static_cast<const uint8_t*>(mapped),volume_size,digest,0) && !memcmp(digest,volume_sha,sizeof(digest)))
    volume_art=static_cast<const uint8_t*>(mapped);
  else ESP_LOGE("study","Volume art verification failed");
#endif
  artwork=static_cast<uint8_t*>(heap_caps_malloc(artwork_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!artwork || tinfl_decompress_mem_to_mem(artwork,artwork_bytes,packed_pages,sizeof(packed_pages)-1,1)!=artwork_bytes){
    ESP_LOGE("study","Page art allocation or decoding failed");return;
  }
#ifdef STUDY_LIVE
  text_art=static_cast<uint8_t*>(heap_caps_malloc(text_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
#ifdef STUDY_EXTERNAL_TEXT
  const void *encoded=nullptr;
  esp_partition_mmap_handle_t text_mapping{};
  if(!part || esp_partition_mmap(part,text_offset,text_packed_size,ESP_PARTITION_MMAP_DATA,&encoded,&text_mapping)!=ESP_OK){
    ESP_LOGE("study","Text artwork missing");return;
  }
  const bool text_ok=text_art && !mbedtls_sha256(static_cast<const uint8_t*>(encoded),text_packed_size,digest,0) &&
    !memcmp(digest,text_sha,sizeof(digest)) && tinfl_decompress_mem_to_mem(text_art,text_bytes,encoded,text_packed_size,1)==text_bytes;
  esp_partition_munmap(text_mapping);
#else
  const bool text_ok=text_art && tinfl_decompress_mem_to_mem(text_art,text_bytes,packed_text,sizeof(packed_text)-1,1)==text_bytes;
#endif
  if(!text_ok){
    ESP_LOGE("study","Text art allocation or decoding failed");return;
  }
  control_art=static_cast<uint8_t*>(heap_caps_malloc(control_bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!control_art || tinfl_decompress_mem_to_mem(control_art,control_bytes,packed_controls,sizeof(packed_controls)-1,1)!=control_bytes){
    ESP_LOGE("study","Control art allocation or decoding failed");
    return;
  }
#endif
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
  load_display_choice();
#ifdef STUDY_SCREEN_OPTIONS
  apply_screen_profile(fleet.active().screen,false);
#endif
  scanout.draw_overlay=draw_diagnostic_badges;
  scanout.restore_overlay=[](Scanout::Slot *slot){copy_badge_background(slot,false);};
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
#ifdef STUDY_CARD_ART
  if(lcd)card_assets_ready();
#endif
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
#ifdef STUDY_LIVE
    if(bell_enabled && !bell_client.reserve_frames())ESP_LOGW("study","Camera buffer reservation failed");
#endif
    if(scanout.active && blender)nav.begin();
#ifdef STUDY_PALETTE_PICKER
#ifdef STUDY_SCREEN_OPTIONS
    apply_screen_profile(fleet.active().screen,true);
#else
    nvs_handle_t prefs;
    if(palette.available() && nvs_open(display_namespace,NVS_READONLY,&prefs)==ESP_OK){
      uint8_t value=0;
      const bool restore=nvs_get_u8(prefs,"palette",&value)==ESP_OK && value>0 && value<6;
      nvs_close(prefs);
      if(restore){
        nav.use_palette_memory();
        if(palette.choose(value,scratch))show(home,0);else nav.restore_chunks();
      }
    }
#endif
#endif
    if(scanout.active && blender){
      page_done=xSemaphoreCreateBinary();
      if(page_done)xTaskCreatePinnedToCore(decode_page_task,"study_page",24576,nullptr,1,&page_worker,xPortGetCoreID()^1);
    }
  }
}
#ifdef STUDY_LIVE
static constexpr int colour_hues[]={0,20,40,60,120,180,200,220,260,290,320,340};
static int warmth_percent(int i){
  const auto &d=ha_lights.detail(i);
  if(d.kelvin<0 || d.maximum<=d.minimum)return 50;
  return std::clamp(int(std::lround(100.*(d.kelvin-d.minimum)/(d.maximum-d.minimum))),0,100);
}
static void draw_light_sheet(bool background){
  const int i=light_index();
  if(i<0 || light_sheet==LightSheet::closed || !page_pixels)return;
  const auto &d=ha_lights.detail(i);
  const Rect screen{0,0,width,height};
  if(light_sheet==LightSheet::colour){
    if(background)control_patch(page_pixels,colour_sheets[i],screen);
    const int p=sheet_drag>=0?sheet_drag:std::clamp(int(std::lround(std::max(0,d.hue)/3.6)),0,100);
    const int hue=sheet_drag>=0?int(std::lround(p*3.6)):d.hue;
    for(int j=0;j<12;j++)
      control_patch(page_pixels,swatch_modes[i][hue>=0 && std::abs(hue-colour_hues[j])<10][j],colour_swatches[i][j]);
    control_patch(page_pixels,hue_modes[i][p][0],hue_rail[i]);
    control_patch(page_pixels,hue_modes[i][p][1],hue_label[i]);
  }else{
    if(background)control_patch(page_pixels,more_pages[i],screen);
    bool included=fleet.active().members[i];
    if(edit_waiting && edit_slot==i+2)included=!included;
    control_patch(page_pixels,more_checks[i][int(included)+(edit_slot==i+2 && edit_feedback==2?2:0)],more_member[i]);
    if(warmth_slider[i].w && (sheet_drag>=0 || d.kelvin>=0)){
      const int p=sheet_drag>=0?sheet_drag:warmth_percent(i);
      control_patch(page_pixels,warmth_modes[i][p][0],warmth_rail[i]);
      control_patch(page_pixels,warmth_modes[i][p][1],warmth_label[i]);
    }
    if(effect_starts[i]!=effect_starts[i+1]){
      int selected=effect_starts[i];
      for(int n=selected;n<effect_starts[i+1];n++)if(d.effect==effect_names[n])selected=n;
      control_patch(page_pixels,effect_selected[selected],effect_open[i]);
    }
    if(light_sheet==LightSheet::effects)control_patch(page_pixels,effect_menu_art[i],effect_menus[i]);
  }
  ++revision;blit(0,0,width,height,page_pixels);
}
static void set_light_sheet(LightSheet next){
  if(next==LightSheet::closed){show(current,0);return;}
  light_sheet=next;sheet_drag=-1;draw_light_sheet(true);
}
static bool sheet_touch(int x,int y){
  const int i=light_index();
  if(i<0)return false;
  if(light_sheet==LightSheet::closed){
    if(!down && more_open.contains(x,y)){down=true;pressed=-140;return true;}
    return pressed==-140;
  }
  const auto &rail=light_sheet==LightSheet::colour?hue_slider[i]:warmth_slider[i];
  if(!down){
    down=true;x0=x;y0=y;
    if(light_sheet!=LightSheet::effects && rail.contains(x,y))sheet_drag=0;
  }
  if(sheet_drag>=0){
    sheet_drag=std::clamp(int(std::lround((x-rail.x)*100./rail.w)),0,100);
    draw_light_sheet(false);
  }
  dx=x-x0;dy=y-y0;return true;
}
static bool sheet_release(){
  const int i=light_index();
  if(i<0 || !down)return false;
  if(pressed==-140){
    down=false;pressed=-2;set_light_sheet(LightSheet::more);return true;
  }
  if(light_sheet==LightSheet::closed)return false;
  const int x=x0+dx,y=y0+dy;
  down=false;pressed=-2;
  using Property=decltype(ha_lights)::Property;
  if(sheet_drag>=0){
    const int p=sheet_drag;sheet_drag=-1;
    const auto &d=ha_lights.detail(i);
    if(light_sheet==LightSheet::colour)ha_lights.adjust(i,Property::colour,std::lround(p*3.6));
    else ha_lights.adjust(i,Property::warmth,std::lround(d.minimum+(d.maximum-d.minimum)*p/100.));
    draw_light_sheet(false);
  }else if(std::abs(dx)<35 && std::abs(dy)<35){
    if(light_sheet==LightSheet::effects){
      for(int n=effect_starts[i];n<effect_starts[i+1];n++)if(effect_rows[n].contains(x,y))
        ha_lights.adjust(i,Property::effect,0,effect_names[n]);
      set_light_sheet(LightSheet::more);
    }else if(light_sheet==LightSheet::colour){
      if(colour_back[i].contains(x,y))set_light_sheet(LightSheet::more);
      else for(int n=0;n<12;n++)if(colour_swatches[i][n].contains(x,y)){
        ha_lights.adjust(i,Property::colour,colour_hues[n]);draw_light_sheet(false);break;
      }
    }else if(more_back[i].contains(x,y))set_light_sheet(LightSheet::closed);
    else if(more_member[i].contains(x,y))edit_scene(i+2);
    else if(colour_open[i].contains(x,y))set_light_sheet(LightSheet::colour);
    else if(effect_open[i].contains(x,y))set_light_sheet(LightSheet::effects);
  }
  return true;
}
// GT911 reports the full active contact set on each update. Once a chord is
// armed, no remaining finger may release a slider or tap a control underneath.
static bool chord_armed=false,chord_blocked=false,chord_dim=false;
static int64_t chord_start=0,chord_next=0;
static int chord_direction=-1,chord_peak=0,chord_level=0;
static std::array<int,light_count> chord_weights{},chord_last{},chord_memory{};
static std::array<int,5> chord_ids{},chord_x{},chord_y{};
static bool chord_loaded=false;
static void remember_chord(const std::array<int,light_count> &values){
  if(!gesture_remember || std::none_of(values.begin(),values.end(),[](int v){return v>0;}) || chord_memory==values)return;
  chord_memory=values;
  nvs_handle_t h;
  if(nvs_open(display_namespace,NVS_READWRITE,&h)==ESP_OK){
    if(nvs_set_blob(h,"light_chord",values.data(),sizeof(values))==ESP_OK)nvs_commit(h);
    nvs_close(h);
  }
}
static void load_chord(){
  if(chord_loaded)return;
  chord_loaded=true;nvs_handle_t h;
  if(gesture_remember && nvs_open(display_namespace,NVS_READONLY,&h)==ESP_OK){
    size_t n=sizeof(chord_memory);
    if(nvs_get_blob(h,"light_chord",chord_memory.data(),&n)!=ESP_OK || n!=sizeof(chord_memory))chord_memory.fill(0);
    nvs_close(h);
  }
}
static void finish_chord(bool tap){
  if(chord_dim){chord_direction=-chord_direction;remember_chord(chord_last);}
  else if(tap){
    std::array<int,light_count> previous{};
    const auto &p=fleet.active();
    for(int i=0;i<light_count;i++)if(p.members[i])previous[i]=std::max(0,ha_lights.confirmed(i));
    const bool any=std::any_of(previous.begin(),previous.end(),[](int value){return value>0;});
    if(any)remember_chord(previous);
    for(int i=0;i<light_count;i++)if(p.members[i] && ha_lights.confirmed(i)>=0)
      ha_lights.request(i,any?0:gesture_remember && chord_memory[i]>0?chord_memory[i]:p.bright[i]);
  }
  chord_armed=false;chord_dim=false;chord_blocked=true;
}
static void chord_tick(){
  if(!chord_armed || clock_ms()<chord_next)return;
  if(!ha_connected()){finish_chord(false);return;}
  if(!chord_dim){
    chord_dim=true;chord_peak=0;chord_last.fill(0);chord_weights.fill(0);
    const auto &p=fleet.active();
    for(int i=0;i<light_count;i++)if(p.members[i] && ha_lights.detail(i).dimmable && ha_lights.confirmed(i)>=0){
      chord_weights[i]=std::max(0,ha_lights.confirmed(i));chord_peak=std::max(chord_peak,chord_weights[i]);
    }
    chord_level=chord_peak;
    if(!chord_peak){
      for(int i=0;i<light_count;i++)if(p.members[i] && ha_lights.detail(i).dimmable && ha_lights.confirmed(i)>=0){
        chord_weights[i]=gesture_remember && chord_memory[i]>0?chord_memory[i]:p.bright[i]>0?p.bright[i]:100;
        chord_peak=std::max(chord_peak,chord_weights[i]);
      }
      chord_level=1;
    }
    if(chord_level<=1)chord_direction=1;else if(chord_level>=100)chord_direction=-1;
  }
  if(!chord_peak){chord_next=INT64_MAX;return;}
  chord_level=std::clamp(chord_level+chord_direction*4,1,100);
  for(int i=0;i<light_count;i++)if(chord_weights[i]){
    const int level=std::max(1,int(std::lround(double(chord_weights[i])*chord_level/chord_peak)));
    if(level!=chord_last[i] && ha_lights.confirmed(i)>=0)ha_lights.request(i,level);
    chord_last[i]=level;
  }
  last_activity=clock_ms();chord_next=(chord_level==1 || chord_level==100)?INT64_MAX:last_activity+200;
}
template<class Touches> static bool observe_touches(const Touches &touches){
  int active=0;
  for(const auto &point:touches)if(point.state==1 || point.state==2)++active;
  observed_touches=std::max(observed_touches,active);
  if(!gesture_points)return false;
  if(active>gesture_points){finish_chord(false);return true;}
  if(chord_blocked)return true;
  if(chord_armed && active<gesture_points){finish_chord(clock_ms()-chord_start>=50);return true;}
  if(active!=gesture_points)return false;
  if(!chord_armed){
    load_chord();down=false;pressed=-2;dragging=false;preview_brightness=sheet_drag=volume_drag=seek_drag=-1;
    climate_drag=false;climate_preview=NAN;
    chord_armed=true;chord_dim=false;chord_start=last_activity=clock_ms();chord_next=chord_start+gesture_hold_ms;
    int n=0;for(const auto &p:touches)if(p.state==1 || p.state==2){chord_ids[n]=p.id;chord_x[n]=p.x;chord_y[n++]=p.y;}
  }else if(!chord_dim){
    for(const auto &p:touches)if(p.state==1 || p.state==2){
      int i=0;while(i<gesture_points && chord_ids[i]!=p.id)++i;
      if(i==gesture_points || std::hypot(double(p.x)-chord_x[i],double(p.y)-chord_y[i])>36){finish_chord(false);break;}
    }
  }
  return true;
}
#endif
static void touch(int x,int y) {
  bench_demo=false;
#ifdef STUDY_LIVE
  last_activity=clock_ms();
  if(identify_until){identify_until=0;show(current,0);apply_brightness();wake_touch=true;return;}
  if(wake_touch)return;
#ifdef STUDY_CARD_BELL
  if(current==doorbell && card_bell_active){
    if(!down){x0=x;y0=y;down=true;pressed=-163;}
    dx=x-x0;dy=y-y0;return;
  }
#endif
#ifdef STUDY_CARD_PLAYER
  if((theme_picker_open || pressed==-162 || (current==display_page && !picker_open && card_choice_hits[0].contains(x,y))) &&
     (!down || pressed==-162)){
    if(!down){x0=x;y0=y;down=true;pressed=-162;}
    dx=x-x0;dy=y-y0;return;
  }
#endif
#ifdef STUDY_CARD_ART
  if(card_page_visible){
    if(!down){
      x0=x;y0=y;touched_at=last_activity;
#ifdef STUDY_CARD_SETTINGS
      settings_down_offset=settings_offset;
#endif
    }
#ifdef STUDY_CARD_PLAYER
    if(moving){nav.cancel();moving=false;blit(0,0,width,height,page_pixels);}
#endif
    down=true;dx=x-x0;dy=y-y0;
#ifdef STUDY_CARD_OVERLAYS
    if(open_card_light>=0 || volume_open){
      const bool volume=volume_open;
      const auto &r=volume?music_overlay().slider:detail_layout(open_card_light).warmth;
      if(r.w && r.contains(x0,y0)){
        auto &drag=volume?volume_drag:sheet_drag;
        drag=std::clamp(int(std::lround(100.*(x-r.x)/r.w)),0,100);
        const bool ok=volume?paint_card_popup(true,page_pixels):paint_card_detail(open_card_light,page_pixels);
        if(ok){++revision;blit(0,0,width,height,page_pixels);}
      }
      return;
    }
    if(queue_open)return;
#endif
#ifdef STUDY_CARD_SETTINGS
    if(card_page==CardPage::settings && settings_scroll_pixels){
      const auto &view=card_settings_views[(card_theme*6+card_mode)*2+int(diagnostics_enabled)];
#ifdef STUDY_CARD_BACKLIGHT
      const auto &track=card_light_rects[card_theme][0][0];
      if(y0<view.height && x0>=track.x && x0<track.x+track.w && y0+settings_down_offset>=track.y && y0+settings_down_offset<track.y+track.h){
        preview_brightness=std::clamp(((x-track.x)*100+track.w/2)/track.w,0,100);
        if(preview_brightness!=shown_brightness)update_settings_level(preview_brightness);
        return;
      }
#endif
      if(y0<view.height && std::abs(dy)>8 && std::abs(dy)>std::abs(dx)){
        settings_offset=std::clamp(settings_down_offset-dy,0,view.scroll);
        copy_settings_window(page_pixels,view.height,settings_offset);
        ++revision;blit(0,0,width,height,page_pixels);return;
      }
    }
#endif
#ifdef STUDY_CARD_LIBRARY
    if(library_open){
      const auto &l=library_layout();
      if(!dx && !dy)library_down_scroll=library_scroll;
      if(l.viewport.contains(x0,y0) && std::abs(dy)>8 && !library.waiting){
        const int limit=std::max(0,int((library.total+l.cols-1)/l.cols)*l.step-l.viewport.h);
        int next=std::clamp(library_down_scroll-dy,0,limit);
        if(next!=library_scroll){
          library_scroll=next;
          const size_t pos=size_t(next/l.step)*l.cols;
          if(pos<library.first || pos>=library.first+library.batch)library.get(pos/library.batch*library.batch);
          if(paint_card_library()){++revision;blit(0,0,width,height,page_pixels);}
        }
      }
      return;
    }
#endif
#ifdef STUDY_CARD_PLAYER
    if(card_page==CardPage::media && player().can_seek && player().duration && seek_slider.contains(x0,y0)){
      seek_drag=std::clamp(int(std::lround(double(x-seek_slider.x)*player().duration/seek_slider.w)),0,player().duration);
      if(paint_card_player(card_theme,card_mode,page_pixels,true)){++revision;blit(0,0,width,height,page_pixels);}
      return;
    }
#endif
    if(card_page==CardPage::lights && (card_finger || card_lights_page.slider_at(x0,y0))){
      if(card_lights_page.touch(x,y,ha_lights)){
        card_finger=true;++revision;blit(0,0,width,height,page_pixels);
      }
    }
    return;
  }
#endif
  if(current==idle){
    wake_touch=true;blanked=false;
#ifdef STUDY_CARD_FIELDS
    if(!card_wake || !show_card_root(wake_page,card_theme,card_mode))
#endif
      show(wake_page,0);
    apply_brightness();return;
  }
  if(!moving && sheet_touch(x,y))return;
#ifdef STUDY_PALETTE_PICKER
  if(!moving && palette.available() && current==display_page && (picker_open || pressed==-161 || (!down && palette_buttons[0].contains(x,y)))){
    if(!down){down=true;pressed=-161;x0=x;y0=y;}
    dx=x-x0;dy=y-y0;return;
  }
#endif
#ifdef USE_ESP32_HOSTED
  if(!moving && current==settings_page && (network_open || pressed==-160 || (!down && wifi_button.contains(x,y)))){
    if(!down){down=true;pressed=-160;x0=x;y0=y;wifi_touch_scroll=wifi_scroll;}
    dx=x-x0;dy=y-y0;
    if(network_open && wifi_selected<0 && std::abs(dy)>12){
      wifi_scroll=std::clamp(wifi_touch_scroll-dy,0,wifi_scroll_limit());paint_network();
    }
    return;
  }
#endif
#ifndef STUDY_ARCHITECTURAL_ONLY
  if(!moving && current==diagnostics_page && (pressed==-159 || (!down && (diagnostic_pass>=0 || (diagnostics_enabled && scroll_button.contains(x,y)))))){
    if(!down){down=true;pressed=-159;x0=x;y0=y;}
    dx=x-x0;dy=y-y0;return;
  }
#endif
  if(!moving && current==diagnostics_page && (pressed==-158 || (!down && (diagnostics_enabled?diagnostic_on_button:diagnostic_button).contains(x,y)))){
    if(!down){down=true;pressed=-158;x0=x;y0=y;}
    dx=x-x0;dy=y-y0;return;
  }
  if(!moving && current==media && !volume_open && !queue_open && !speakers_open &&
      (pressed==-157 || (!down && (browse_button.contains(x,y) || (library_open && y<speaker_end))))){
    if(!down){down=true;pressed=-157;x0=x;y0=y;library_down_scroll=library_scroll;}
    dx=x-x0;dy=y-y0;
    if(library_open && y0>=library_list.y && std::abs(dy)>8 && !library.waiting){
      const int cols=library_steps[library_mode][0],step=library_steps[library_mode][1];
      const int max_scroll=std::max(0,int((library.total+cols-1)/cols)*step-library_list.h);
      const int previous=library_scroll;
      library_scroll=std::clamp(library_down_scroll-dy,0,max_scroll);
      if(previous==library_scroll)return;
      const size_t first=(library_scroll/step)*cols,offset=first/library.batch*library.batch;
      if(library.total && (first<library.first || first>=library.first+library.batch))library.get(offset);
      paint_library(library_scroll-previous);++revision;blit(0,0,width,height,page_pixels);
    }
    return;
  }
  if(!moving && current==media && !volume_open && !queue_open &&
     (pressed==-156 || (!down && (speaker_button.contains(x,y) || (speakers_open && y<speaker_end))))){
    if(!down){x0=x;y0=y;down=true;pressed=-156;speaker_down_scroll=speaker_scroll;}
    dx=x-x0;dy=y-y0;
    if(speakers_open && y0>=speaker_top && std::abs(dy)>8){
      speaker_scroll=std::clamp(speaker_down_scroll-dy,0,speaker_max_scroll);
      transport_fields();++revision;blit(0,0,width,height,page_pixels);
    }
    return;
  }
  if(!moving && current==settings_page && (!down || pressed==-154 || pressed==-155)){
    if(!down && (mini_button.contains(x,y) || reload_button.contains(x,y))){
      down=true;pressed=mini_button.contains(x,y)?-154:-155;x0=x;y0=y;dx=dy=0;return;
    }
    if(pressed==-154 || pressed==-155){dx=x-x0;dy=y-y0;return;}
  }
  if(current==media && !moving && !volume_open && (queue_open || (!down && queue_button.contains(x,y)) || pressed==-153)){
    if(!down){x0=x;y0=y;down=true;pressed=-153;}
    dx=x-x0;dy=y-y0;return;
  }
  if(!down && current==home && player().playing && home_strip.contains(x,y)){
    down=true;pressed=home_play.contains(x,y)?-151:-152;x0=x;y0=y;dx=dy=0;return;
  }
  if(pressed==-151 || pressed==-152){dx=x-x0;dy=y-y0;return;}
  if(!volume_open && current==media && !moving &&
     (seek_drag>=0 || (!down && player().available && player().can_seek && player().duration && seek_slider.contains(x,y)))){
    down=true;pressed=-2;seek_drag=std::clamp(int(std::lround(double(x-seek_slider.x)*player().duration/seek_slider.w)),0,player().duration);
    progress_fields();++revision;blit(0,0,width,height,page_pixels);return;
  }
  if(current==media && !moving && (volume_open || (!down && volume_button.contains(x,y)) || pressed==-150)){
    if(!down){
      down=true;x0=x;y0=y;pressed=-150;
      if(volume_open && volume_slider.contains(x,y))volume_drag=std::max(0,player().volume);
    }
    dx=x-x0;dy=y-y0;
    if(volume_drag>=0){
      volume_drag=std::clamp(int(std::lround((x-volume_slider.x)*100./volume_slider.w)),0,100);
      paint_volume();++revision;blit(0,0,width,height,page_pixels);
    }
    return;
  }
#endif
  const int i=light_index();
  if(!down) {
    if(moving){nav.cancel();await_page();moving=false;blit(0,0,width,height,page_pixels);}
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
#ifdef STUDY_CARD_BELL
  if(pressed==-163){
    down=false;pressed=-2;
    if(std::abs(dx)<24 && std::abs(dy)<24 && bell_view().close.contains(x0,y0))go(-1);
    return;
  }
#endif
#ifdef STUDY_LIVE
  if(chord_armed || chord_blocked){
    if(chord_armed)finish_chord(clock_ms()-chord_start>=50);
    chord_blocked=false;wake_touch=false;down=false;pressed=-2;return;
  }
#endif
#ifdef STUDY_CARD_PLAYER
  if(pressed==-162){
    pressed=-2;down=false;
    if(std::abs(dx)>=24 || std::abs(dy)>=24)return;
    if(!theme_picker_open){open_theme_picker();return;}
    if(card_choice_hits[1].contains(x0,y0)){show(display_page,0);return;}
    for(int i=0;i<3;++i)if(card_choice_hits[i+2].contains(x0,y0)){select_theme(i);return;}
    return;
  }
#endif
#ifdef STUDY_PALETTE_PICKER
  if(pressed==-161){
    down=false;pressed=-2;last_activity=clock_ms();
    if(std::abs(dx)>=24 || std::abs(dy)>=24)return;
    const int x=x0+dx,y=y0+dy;
    if(!picker_open){if(palette_buttons[0].contains(x,y))open_palette();return;}
    if(palette_buttons[1].contains(x,y)){show(display_page,0);return;}
    for(int i=0;i<6;i++)if(palette_buttons[i+2].contains(x,y)){
      if(choose_palette(i))open_palette();
      return;
    }
    return;
  }
#endif
#ifdef USE_ESP32_HOSTED
  if(pressed==-160){
    down=false;pressed=-2;
    if(std::abs(dx)<24 && std::abs(dy)<24)network_action(x0,y0);
    return;
  }
#endif
#ifdef STUDY_LIVE
  last_activity=clock_ms();
  if(wake_touch){wake_touch=false;return;}
#ifdef STUDY_CARD_ART
  if(card_page_visible){
#ifdef STUDY_CARD_EDITOR
    if(current==edit_page || current==members_page){
      if(down && std::abs(dx)<24 && std::abs(dy)<24){
        const auto &v=card_editor_view();
        if(current==edit_page){
          if(v.back.contains(x0,y0))show_card_scene(card_theme,card_mode,CardPage::scenes);
          else if(v.list.contains(x0,y0))open_card_editor(true);
          else for(int i=0;i<2;++i)if(v.saves[i].area.contains(x0,y0))edit_scene(i);
        }else if(v.members_back.contains(x0,y0))open_card_editor(false);
        else for(int i=0;i<light_count;++i)if(v.lights[i].area.contains(x0,y0))edit_scene(i+2);
      }
      down=card_finger=false;pressed=-2;refresh_edit();return;
    }
#endif
#ifdef STUDY_CARD_OVERLAYS
    if(open_card_light>=0){
      const int i=open_card_light;
      using Property=decltype(ha_lights)::Property;
      if(sheet_drag>=0){
        const auto &d=ha_lights.detail(i);
        ha_lights.adjust(i,Property::warmth,std::lround(d.minimum+(d.maximum-d.minimum)*sheet_drag/100.));
        sheet_drag=-1;
      }else if(down && std::abs(dx)<24 && std::abs(dy)<24){
        const auto *h=card_hit(card_theme,card_page,x0,y0);
        if(y0<detail_layout(i).top)show_card_lights(card_theme,card_mode);
        else if(h && h->action==CardAction::membership)edit_scene(i+2);
        else if(h && h->action==CardAction::colour && h->arg>=0 && h->arg<int(std::size(colour_hues)))
          ha_lights.adjust(i,Property::colour,colour_hues[h->arg]);
        else if(h && h->action==CardAction::effect && h->arg>=0 && effect_starts[i]+h->arg<effect_starts[i+1])
          ha_lights.adjust(i,Property::effect,0,effect_names[effect_starts[i]+h->arg]);
      }
      if(open_card_light>=0 && paint_card_detail(i,page_pixels)){++revision;blit(0,0,width,height,page_pixels);}
    }else if(volume_open){
      if(volume_drag>=0){player().set_volume(volume_drag);volume_drag=-1;}
      else if(down && std::abs(dx)<24 && std::abs(dy)<24 &&
              (music_overlay().close.contains(x0,y0) || !music_overlay().panel.contains(x0,y0)))show_card_player(card_theme,card_mode);
    }else if(queue_open){
      if(down && std::abs(dx)<24 && std::abs(dy)<24 && y0<music_overlay().queue[card_queue_state()].top)show_card_player(card_theme,card_mode);
    }else if(card_page==CardPage::home && player().playing && down && std::abs(dx)<24 && std::abs(dy)<24 &&
             Rect{music_overlay().strip[mini_art_enabled].tile.x,music_overlay().strip[mini_art_enabled].tile.y,
                  music_overlay().strip[mini_art_enabled].tile.w,music_overlay().strip[mini_art_enabled].tile.h}.contains(x0,y0)){
      if(music_overlay().strip[mini_art_enabled].play.contains(x0,y0))player().press(p4_runtime::MediaClient::play_pause);
      else show_card_player(card_theme,card_mode);
    }else
#endif
    if(card_finger)card_lights_page.release(ha_lights);
#ifdef STUDY_CARD_BACKLIGHT
    else if(card_page==CardPage::settings && preview_brightness>=0){
      manual_brightness=std::clamp(preview_brightness,int(backlight_min),100);
      override_until=clock_ms()+600000;preview_brightness=-1;apply_brightness();
      if(shown_brightness!=manual_brightness)update_settings_level(manual_brightness);
    }
#endif
#ifdef STUDY_CARD_LIBRARY
    else if(library_open){
      if(down && std::abs(dx)<24 && std::abs(dy)<24){
        const auto &l=library_layout();
        if(l.back.contains(x0,y0)){
          if(library.folders.empty())show_card_player(card_theme,card_mode);
          else {library_scroll=0;library.up();}
        }else if(l.toggle.contains(x0,y0)){
          library_scroll=0;library_mode=1-library_mode;
          const bool base_tiles=fleet.active().screen.tiles;
          remember_screen("libview",library_mode,(library_steps[0][0]>1)==base_tiles?0:1);
          card_page=library_steps[library_mode][0]==1?CardPage::library_alt:CardPage::library;
          report_screen();if(library.first)library.get(0);
        }else if(l.viewport.contains(x0,y0) && !library.waiting){
          const int column=l.cols>1?(x0-l.viewport.x)/l.spacing:0;
          const int row=(y0-l.viewport.y+library_scroll)/l.step;
          const size_t pos=row*l.cols+column;
          if(column<l.cols && pos>=library.first && pos-library.first<library.items.size()){
            const size_t i=pos-library.first;const auto &tile=l.tiles[library.items[i].expand?0:1];
            if(x0-l.viewport.x-column*l.spacing<tile.w && (y0-l.viewport.y+library_scroll)%l.step<tile.h){
              const bool play=!library.items[i].expand && library.items[i].play;
              library.choose(i);
              if(play)show_card_player(card_theme,card_mode);else library_scroll=0;
            }
          }
        }
        if(library_open && paint_card_library()){++revision;blit(0,0,width,height,page_pixels);}
      }
    }
#endif
#ifdef STUDY_CARD_PLAYER
    else if(seek_drag>=0){player().seek(seek_drag);seek_drag=-1;}
#endif
#ifdef STUDY_CARD_SPEAKERS
    else if(card_page==CardPage::speakers){
      if(down && std::abs(dx)<24 && std::abs(dy)<24){
        const auto *link=card_hit(card_theme,card_page,x0,y0);
        if(link && link->arg>=0 && link->arg<speaker_count){
          if(link->action==CardAction::speaker && !transfer_busy){
            select_speaker(link->arg);
#ifdef STUDY_CARD_PLAYER
            if(!show_card_player(card_theme,card_mode))
#endif
              show(media,0);
          }
          else if(link->action==CardAction::transfer)transfer_speaker(link->arg);
        }
#ifdef STUDY_CARD_PLAYER
        else if(!link && y0<card_speaker_top[card_theme*6+card_mode])show_card_player(card_theme,card_mode);
#endif
      }
    }
#endif
#ifdef STUDY_CARD_FIELDS
    else if(down && std::abs(dx)>=90 && std::abs(dx)*2>=std::abs(dy)*3 && clock_ms()-touched_at<=1200){
      const int dest=current+(dx<0?1:-1);
      if(dest>=home && dest<=media){
        depth=0;if(dest!=home)history[depth++]=home;
#ifdef STUDY_CARD_PLAYER
        card_travel=dx<0?24:-24;
#endif
        if(!show_card_root(dest,card_theme,card_mode))show(dest,dx<0?24:-24);
#ifdef STUDY_CARD_PLAYER
        card_travel=14;
#endif
      }
    }
#endif
    else if(down && std::abs(dx)<24 && std::abs(dy)<24){
#ifdef STUDY_CARD_SETTINGS
      if(card_page==CardPage::settings && settings_scroll_pixels){
        const int state=2*card_theme+int(diagnostics_enabled);
        const auto &view=card_settings_views[(card_theme*6+card_mode)*2+int(diagnostics_enabled)];
        if(y0<view.height)for(const auto &h:card_settings_hits){
          const int y=y0+settings_offset;
          if(h.state!=state || x0<h.x || x0>=h.x+h.w || y<h.y || y>=h.y+h.h)continue;
          switch(static_cast<SettingRow>(h.action)){
            case SettingRow::themeRow:show_card_options(card_theme,card_mode,CardPage::theme);break;
            case SettingRow::paletteRow:show_card_options(card_theme,card_mode,CardPage::palette);break;
            case SettingRow::diagRow:
              if(remember_screen("diag",!diagnostics_enabled,fleet.active().screen.diagnostics)){
                diagnostics_enabled=!diagnostics_enabled;report_screen();show_card_options(card_theme,card_mode,CardPage::settings);
              }
              break;
            case SettingRow::saveSoftRow:case SettingRow::saveBrightRow:edit_scene(h.action==int(SettingRow::saveSoftRow)?0:1);break;
            case SettingRow::scrollTestRow:
              card_switching=true;show(diagnostics_page,0);card_switching=false;
              diagnostic_pass=0;diagnostic_frames=0;diagnostic_offset=0;break;
            case SettingRow::reload:depth=0;show(home,0);break;
            case SettingRow::archMiniArt:save_display_choice(!mini_art_enabled);show_card_options(card_theme,card_mode,CardPage::settings);break;
            case SettingRow::bl:
              manual_brightness=std::clamp(int(std::lround(double(x0-h.x)*100/h.w)),int(backlight_min),100);
              override_until=clock_ms()+600000;apply_brightness();break;
#ifdef USE_ESP32_HOSTED
            case SettingRow::wifiRow:
              card_switching=true;show(settings_page,0);card_switching=false;
              network_action(wifi_button.x+wifi_button.w/2,wifi_button.y+wifi_button.h/2);break;
#endif
            default:break;
          }
          down=card_finger=false;pressed=-2;return;
        }
      }
#endif
      auto *link=card_hit(card_theme,card_page,x0,y0);
      if(link)switch(link->action){
#ifdef STUDY_CARD_FIELDS
        case CardAction::back:
#ifdef STUDY_CARD_PLAYER
          if(card_page==CardPage::theme || card_page==CardPage::palette){show_card_options(card_theme,card_mode,CardPage::settings);break;}
#endif
          show_card_scene(card_theme,card_mode,CardPage::home);break;
        case CardAction::open_scenes:show_card_scene(card_theme,card_mode,CardPage::scenes);break;
        case CardAction::open_lights:show_card_lights(card_theme,card_mode);break;
        case CardAction::open_blinds:show_card_room_page(card_theme,card_mode,CardPage::blinds);break;
        case CardAction::preset:{
          const auto &p=fleet.active();
          for(int i=0;i<light_count;++i)if(p.members[i])ha_lights.request(i,link->arg==0?p.soft[i]:link->arg==2?p.bright[i]:0);
          break;
        }
        case CardAction::spDown:case CardAction::spUp:
          if(thermostat.can_adjust())thermostat.set(thermostat.target+(link->action==CardAction::spUp?1:-1)*thermostat.step);
          break;
        case CardAction::open_settings:
#ifdef STUDY_CARD_PLAYER
          if(show_card_options(card_theme,card_mode,CardPage::settings))break;
#endif
          go(settings_page);break;
        case CardAction::open_scene_edit:
#ifdef STUDY_CARD_EDITOR
          open_card_editor(false);
#else
          go(edit_page);
#endif
          break;
#else
        case CardAction::back:show(home,0);break;
        case CardAction::open_scenes:go(scenes);break;
        case CardAction::open_blinds:go(climate_page+1);break;
#endif
        case CardAction::light:
          if(link->arg>=0 && link->arg<light_count){
#ifdef STUDY_CARD_OVERLAYS
            open_card_detail(link->arg);
#else
            go(light0+link->arg);
#endif
          }
          break;
        case CardAction::open_climate:
#ifdef STUDY_CARD_CLIMATE
          show_card_room_page(card_theme,card_mode,CardPage::climate);
#else
          go(climate_page);
#endif
          break;
        case CardAction::open_media:
#ifdef STUDY_CARD_PLAYER
          if(show_card_player(card_theme,card_mode))break;
#endif
          go(media);break;
#ifdef STUDY_CARD_PLAYER
        case CardAction::icoSpk:show_card_speakers(card_theme,card_mode);break;
        case CardAction::pp:player().press(p4_runtime::MediaClient::play_pause);break;
        case CardAction::shuf:player().press(p4_runtime::MediaClient::shuffle);break;
        case CardAction::rep:player().press(p4_runtime::MediaClient::repeat);break;
        case CardAction::next:player().press(p4_runtime::MediaClient::next);break;
        case CardAction::prev:player().press(p4_runtime::MediaClient::previous);break;
        case CardAction::icoSearch:case CardAction::icoMore:case CardAction::mpVolumeButton:{
#ifdef STUDY_CARD_OVERLAYS
          if(link->action!=CardAction::icoSearch){open_card_popup(link->action==CardAction::mpVolumeButton);break;}
#endif
#ifdef STUDY_CARD_LIBRARY
          if(link->action==CardAction::icoSearch){open_card_library();break;}
#endif
          card_switching=true;show(media,0);card_switching=false;
          if(link->action==CardAction::icoSearch){library_open=true;library_scroll=0;library.open(speaker_ids[selected_speaker]);}
          else if(link->action==CardAction::icoMore)queue_open=true;
          else volume_open=true;
          transport_fields();++revision;blit(0,0,width,height,page_pixels);break;
        }
        case CardAction::themeRow:show_card_options(card_theme,card_mode,CardPage::theme);break;
        case CardAction::archMiniArt:
          if(save_display_choice(!mini_art_enabled))show_card_options(card_theme,card_mode,CardPage::settings);
          break;
#ifdef USE_ESP32_HOSTED
        case CardAction::wifiRow:{
          card_switching=true;show(settings_page,0);card_switching=false;
          network_action(wifi_button.x+wifi_button.w/2,wifi_button.y+wifi_button.h/2);break;
        }
#endif
        case CardAction::paletteRow:show_card_options(card_theme,card_mode,CardPage::palette);break;
        case CardAction::choose_theme:select_theme(link->arg);break;
        case CardAction::choose_palette:
          if(choose_palette(link->arg))show_card_options(card_theme,link->arg,CardPage::palette);
          break;
#endif
        default:break;
      }
    }
    down=card_finger=false;pressed=-2;return;
  }
#endif
  if(sheet_release())return;
  if(pressed==-159){
    pressed=-2;down=false;
    if(std::abs(dx)>=24 || std::abs(dy)>=24)return;
    if(diagnostic_pass>=0){
#ifdef STUDY_CARD_LIBRARY
      if(selected_theme<2){
        if(library_layout().back.contains(x0,y0)){
          release_library_backgrounds();show_card_options(selected_theme,card_mode,CardPage::settings);
        }
      }else
#endif
      if(browse_back.contains(x0,y0))show(diagnostics_page,0);
    }
    else if(previous_pixels && scroll_button.contains(x0,y0)){diagnostic_pass=0;diagnostic_frames=0;diagnostic_offset=0;}
    return;
  }
  if(pressed==-158){
    down=false;pressed=-2;
    if(std::abs(dx)<24 && std::abs(dy)<24 &&
#ifdef STUDY_SCREEN_OPTIONS
       remember_screen("diag",!diagnostics_enabled,fleet.active().screen.diagnostics)
#else
       save_preference("diag",!diagnostics_enabled)
#endif
    ){
      diagnostics_enabled=!diagnostics_enabled;show(diagnostics_page,0);
#ifdef STUDY_SCREEN_OPTIONS
      report_screen();
#endif
    }
    return;
  }
  if(pressed==-157){
    down=false;pressed=-2;
    if(std::abs(dx)>24 || std::abs(dy)>24)return;
    const int x=x0+dx,y=y0+dy;
    if(!library_open){
      if(!browse_button.contains(x,y))return;
      library_scroll=0;library_open=true;library.open(speaker_ids[selected_speaker]);
    }else if(browse_back.contains(x,y)){
      if(library.folders.empty()){show(media,0);return;}
      library_scroll=0;library.up();
    }else if(browse_switch.contains(x,y)){
      library_mode=1-library_mode;
#ifdef STUDY_SCREEN_OPTIONS
      remember_screen("libview",library_mode,(library_steps[0][0]>1)==fleet.active().screen.tiles?0:1);
      report_screen();
#else
      save_preference("libview",library_mode!=0);
#endif
      library_scroll=0;if(library.first)library.get(0);
    }else if(library_list.contains(x,y) && !library.waiting){
      const int cols=library_steps[library_mode][0],step=library_steps[library_mode][1];
      const int row=(y-library_list.y+library_scroll)/step;
      const int col=cols==1?0:(x-library_list.x)/int(library_steps[library_mode][2]);
      const size_t pos=row*cols+col;
      if(pos>=library.first && pos-library.first<library.items.size()){
        const size_t i=pos-library.first;bool play=!library.items[i].expand && library.items[i].play;
        library.choose(i);if(play){show(media,0);return;}library_scroll=0;
      }
    }
    paint_library();++revision;blit(0,0,width,height,page_pixels);return;
  }
  if(pressed==-156){
    down=false;pressed=-2;
    if(std::abs(dx)>24 || std::abs(dy)>24)return;
    const int x=x0+dx,y=y0+dy;
    if(!speakers_open){
      if(!speaker_button.contains(x,y))return;
      speakers_open=true;speaker_scroll=0;if(!transfer_busy)transfer_status=nullptr;
    }else if(speaker_back.contains(x,y)){show(media,0);return;}
    else if(y>=speaker_top && y<speaker_end && !transfer_busy){
      int top=speaker_top-speaker_scroll;
      for(int i=0;i<speaker_count;i++){
        const int h=speaker_rows[i][speaker_variant(i)][2];const auto *r=speaker_rects[i];
        if(y>=top && y<top+h && x>=int(r[0]) && x<int(r[0]+r[1])){
          if(x>=int(r[0]+r[2]))transfer_speaker(i);else select_speaker(i);
          break;
        }
        top+=h;
      }
    }
    if(!speakers_open){show(media,0);return;}
    transport_fields();++revision;blit(0,0,width,height,page_pixels);return;
  }
  if(pressed==-154 || pressed==-155){
    const bool preference=pressed==-154;
    down=false;pressed=-2;
    if(std::abs(dx)<35 && std::abs(dy)<35){
      if(preference && save_display_choice(!mini_art_enabled)){status_fields();++revision;blit(0,0,width,height,page_pixels);}
      else if(!preference){depth=0;last_activity=clock_ms();load_display_choice();show(home,0);}
    }
    return;
  }
  if(pressed==-153){
    down=false;pressed=-2;
    if(std::abs(dx)<35 && std::abs(dy)<35){
      if(queue_open && queue_back.contains(x0+dx,y0+dy))show(media,0);
      else if(!queue_open && queue_button.contains(x0+dx,y0+dy)){
        queue_open=true;transport_fields();++revision;blit(0,0,width,height,page_pixels);
      }
    }
    return;
  }
  if(seek_drag>=0){
    player().seek(seek_drag);seek_drag=-1;down=false;pressed=-2;return;
  }
  if(pressed==-151 || pressed==-152){
    const bool toggle=pressed==-151;down=false;pressed=-2;
    if(std::abs(dx)<40 && std::abs(dy)<40){
      if(toggle)player().press(p4_runtime::MediaClient::play_pause);else go(media);
    }
    dx=dy=0;return;
  }
  if(current==media && pressed==-150){
    down=false;pressed=-2;
    if(volume_drag>=0){player().set_volume(volume_drag);volume_drag=-1;}
    else if(!volume_open && volume_button.contains(x0+dx,y0+dy))volume_open=true;
    else if(volume_open && (volume_close.contains(x0+dx,y0+dy) || !volume_popup.contains(x0+dx,y0+dy))){
      show(media,0);return;
    }
    paint_volume();++revision;blit(0,0,width,height,page_pixels);return;
  }
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
      else if(pressed<=-120 && pressed>=-124)player().press(static_cast<p4_runtime::MediaClient::Control>(-120-pressed));
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
  if(current==idle){
    blanked=false;
#ifdef STUDY_CARD_FIELDS
    if(!card_wake || !show_card_root(wake_page,card_theme,card_mode))
#endif
      show(wake_page,0);
  }
#ifdef STUDY_CARD_FIELDS
  if(current!=doorbell)card_ring_return=card_page_visible;
#endif
  last_activity=clock_ms();
#endif
  down=false;dragging=false;pressed=-2;
  if(current!=doorbell)go(doorbell);
#ifdef STUDY_LIVE
  apply_brightness();
#endif
  deadline=clock_ms()+60000;
}
static void close_ring(){if(current==doorbell)go(-1);}
#ifdef STUDY_LIVE
static int bell_status=-1;
static bool pulled_video=false;
static unsigned bell_frames=0;
static int bell_draw_w=0,bell_draw_h=0;
static void paint_bell_status(int next){
  if(next==bell_status)return;
  bell_status=next;
#ifdef STUDY_CARD_BELL
  if(card_bell_active)apply_player_patch(bell_view().footers[next],page_pixels,card_bell_file);
  else
#endif
    text_background(page_pixels,width,scratch,bell_footer,bell_footers[next][0],bell_footers[next][1]);
  ++revision;blit(0,0,width,height,page_pixels);
}
static void camera_ring(bool test){
  static int64_t session_start;
  const bool already=current==doorbell && pulled_video;
  const auto now=clock_ms();
  if(!already)session_start=now;
  ring();deadline=std::min(now+bell_seconds*1000,session_start+300000);
  if(already)return;
  pulled_video=true;bell_status=-1;bell_frames=0;bell_draw_w=bell_draw_h=0;
#ifdef STUDY_CARD_BELL
  card_bell_active=card_assets_ready() && read_player_patch(bell_view().base,page_pixels,card_bell_file) &&
                   apply_player_patch(bell_view().headers[test],page_pixels,card_bell_file);
  if(!card_bell_active)
#endif
    text_background(page_pixels,width,scratch,bell_header,bell_headers[test][0],bell_headers[test][1]);
  paint_bell_status(0);bell_client.open(fleet.online());
}
#endif
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
  if(identify_until){
    if(clock_ms()<identify_until){apply_brightness();return;}
    identify_until=0;blit(0,0,width,height,page_pixels);
  }
#ifdef STUDY_CARD_PLAYER
  static bool waiting_for_theme=true;
  if(waiting_for_theme && card_state.load()==CardState::ready && !down && !moving){
    if(selected_theme<2 && current==home)show_card_root(home,selected_theme,card_mode);
    waiting_for_theme=false;
  }
#endif
  chord_tick();
#ifdef USE_ESP32_HOSTED
  network_refresh();
#endif
  measure_refresh();
  static int reported_fps=-1,reported_connection=-1;
  if(diagnostics_enabled && !blanked && !moving && !down && diagnostic_pass<0 && current!=doorbell && page_pixels){
    const int connected=ha_connected();
    if(reported_fps!=refresh_fps || reported_connection!=connected){
      const auto &r=diag_disconnected.rect;
      scanout.count_frame=false;
      blit(0,r.y,width,r.h,page_pixels+2*width*r.y,width);
      scanout.count_frame=true;
      reported_fps=refresh_fps;reported_connection=connected;
    }
  }
  if(bell_enabled){
    bell_client.listen();
    const bool test=bell_client.test_ring.exchange(false);
    if(test || bell_client.trigger_ring){bell_client.trigger_ring=false;camera_ring(test);}
  }
  const auto now=clock_ms();
  static int64_t previous=now;
  static int64_t next_home_diagnostic=0;
  if(current==home && diagnostics_enabled && !moving && !down && now>=next_home_diagnostic
#if defined(STUDY_CARD_FIELDS) && !defined(STUDY_CARD_DIAGNOSTICS)
     && !card_page_visible
#endif
  ){
    next_home_diagnostic=now+500;
    auto message=home_diagnostic_message();
    if(message!=last_home_diagnostic){
#ifdef STUDY_CARD_DIAGNOSTICS
      if(card_page_visible)show_card_scene(card_theme,card_mode,CardPage::home);
      else
#endif
      {paint_home_diagnostics(message);++revision;blit(0,0,width,height,page_pixels);}
    }
  }
  brightness_now+=(brightness_target-brightness_now)*(adaptive_transition_s>0?
      1-std::exp(-3*std::min(2.0,(now-previous)/1000.)/adaptive_transition_s):1);
  previous=now;
  if(!down && !moving && !bench_demo && !wake_touch && current!=doorbell && current!=idle &&
     idle_timeout_s>0 && now-last_activity>=idle_timeout_s*1000){
#ifdef STUDY_CARD_FIELDS
    card_wake=card_page_visible;
#endif
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
  for(int i=0;i<speaker_count;i++){
    players[i].tick();
    if(i!=selected_speaker && players[i].dirty){speakers_dirty=true;players[i].dirty=false;}
  }
  if(transfer_busy && now>=transfer_until){
    transfer_busy=false;transfer_status="Transfer not confirmed. Check the speakers before retrying.";
    speakers_dirty=true;
  }
  if(speakers_dirty){if(speakers_open)player().dirty=true;speakers_dirty=false;}
  if(library_open){library.tick();if(library.dirty){player().dirty=true;library.dirty=false;}}
#ifndef STUDY_BENCH_TEST
  album_client.select(speaker_ids[selected_speaker],player().picture);
#endif
  if(!moving && !down && current!=doorbell && !bench_demo)update_cover();
#ifndef STUDY_BENCH_TEST
  if(library_open && !library.waiting && !moving && !down)load_library_thumbnail();
#endif
  if(player().dirty && !moving && !down){
    player().dirty=false;
    if(current==media && page_pixels){
#ifdef STUDY_CARD_OVERLAYS
      if(card_page_visible && (volume_open || queue_open))paint_card_popup(volume_open,page_pixels);
      else
#endif
#ifdef STUDY_CARD_LIBRARY
      if(card_page_visible && library_open)paint_card_library();
      else
#endif
#ifdef STUDY_CARD_SPEAKERS
      if(card_page_visible && card_page==CardPage::speakers)paint_card_speakers(card_theme,card_mode,page_pixels,false);
      else
#endif
#ifdef STUDY_CARD_PLAYER
      if(card_page_visible && card_page==CardPage::media)paint_card_player(card_theme,card_mode,page_pixels,false);
      else
#endif
        transport_fields();
      ++revision;blit(0,0,width,height,page_pixels);
    }
#ifdef STUDY_CARD_OVERLAYS
    if(current==home && card_page_visible && card_page==CardPage::home)show_card_scene(card_theme,card_mode,CardPage::home);
#endif
    if(current==home && page_pixels
#ifdef STUDY_CARD_FIELDS
       && !card_page_visible
#endif
    ){home_player();++revision;blit(0,0,width,height,page_pixels);}
  }
  static int64_t next_progress=0;
#ifdef STUDY_CARD_MOTION_GEOMETRY
  if(current==home && player().playing && !down && !moving && now>=next_progress){
    const int theme=card_page_visible?card_theme:2,mode=palette.selection();
    paint_equalizer(page_pixels,theme,theme==2?0:mode,now);
    const auto &bars=eq_bars[theme][mini_art_enabled];
    int left=bars[0].x,top=bars[0].y,right=bars[3].x+bars[3].w,bottom=bars[0].y+bars[0].h;
    if(card_page_visible){
      const auto &r=music_overlay().strip[mini_art_enabled].progress;
      if(r.w && player().duration){
        const int n=std::clamp(int(std::lround(player().position()*r.w/player().duration)),0,r.w);
        for(int y=0;y<r.h;++y)std::fill_n(reinterpret_cast<uint16_t*>(page_pixels)+(y+r.y)*width+r.x,n,eq_accent[theme][mode]);
        left=std::min(left,r.x);top=std::min(top,r.y);right=std::max(right,r.x+r.w);bottom=std::max(bottom,r.y+r.h);
      }
    }
    blit(left,top,right-left,bottom-top,page_pixels+2*(top*width+left),width);
    next_progress=now+80;
  }
#endif
#ifdef STUDY_CARD_PLAYER
  if(progress_active() && card_page_visible && now>=next_progress){
    if(card_page_visible && card_page==CardPage::media)paint_card_player(card_theme,card_mode,page_pixels,true);
    ++revision;blit(0,0,width,height,page_pixels);next_progress=now+125;
  }
#endif
  static int64_t next_status=0;
#ifdef STUDY_CARD_DIAGNOSTICS
  if(card_page_visible && card_page==CardPage::settings && settings_scroll_pixels && !moving && !down && now>=next_status){
    const auto &view=card_settings_views[(card_theme*6+card_mode)*2+int(diagnostics_enabled)];
    settings_live_text(card_theme,card_mode,settings_scroll_pixels,view.height);
    settings_live_text(card_theme,card_mode,settings_tail,view.scroll,view.height);
    copy_settings_window(page_pixels,view.height,settings_offset);
    next_status=now+5000;++revision;blit(0,0,width,height,page_pixels);
  }
#endif
#ifdef STUDY_CARD_BACKLIGHT
  if(card_page_visible && card_page==CardPage::settings && !down && !moving && screen_level()!=shown_brightness)
    update_settings_level(screen_level());
#endif
  if(!down && !moving && diagnostic_pass<0 && page_pixels && (current==room_menu_page || current==diagnostics_page) && now>=next_status){
    status_fields();next_status=now+5000;++revision;blit(0,0,width,height,page_pixels);
  }
  if(current==display_page && page_pixels && !down && !moving && screen_level()!=shown_brightness
#ifdef STUDY_PALETTE_PICKER
     && !picker_open
#endif
  ){
    display_field(screen_level());++revision;blit(0,0,width,height,page_pixels);
  }
  thermostat.tick();
  if(thermostat.dirty && !down && !moving){
    thermostat.dirty=false;
    if((current==home || current==climate_page)
#ifdef STUDY_CARD_FIELDS
       && !card_page_visible
#endif
    ){climate_field();++revision;blit(0,0,width,height,page_pixels);}
  }
  const bool updated=fleet.tick(ha_lights.receiving());
  using PanelAction=p4_runtime::FleetSocket::Action;
  const auto action=moving?PanelAction::none:fleet.take_action();
  if(action==PanelAction::restart)esphome::App.safe_reboot();
  if(action==PanelAction::wake || action==PanelAction::identify){
    blanked=false;last_activity=now;
    if(current==idle)show(wake_page,0);
  }
  if(action==PanelAction::identify){
    show(current,0);
#ifdef STUDY_IDENTIFY
    scanout.copy_pixels(previous_pixels,scanout.visible_pixels(),page_bytes);
    const auto &frame=identify_frames[palette.selection()];
    if(tinfl_decompress_mem_to_mem(scratch,page_bytes,identify_pixels+frame[0],frame[1],1)==page_bytes){
      identify_until=now+10000;identify_phase=-1;apply_brightness();return;
    }
#else
    identify_until=now+10000;
#endif
  }
  if(action==PanelAction::sleep){wake_page=current;show(idle,0);blanked=true;}
  if(action==PanelAction::reload && !moving){show(current,0);last_activity=now;}
  const bool display_result=fleet.display_pending();
  const int result=fleet.result();
#ifdef STUDY_SCREEN_OPTIONS
  static ScreenChoices applied=factory_profile().screen;
  if(updated){
    const auto next=fleet.active().screen;
    if(next.theme!=applied.theme || next.palette!=applied.palette ||
       next.diagnostics!=applied.diagnostics || next.tiles!=applied.tiles || next.mini_art!=applied.mini_art){
      apply_screen_profile(next,true);applied=next;
    }
  }
  if(pending_screen_report && !fleet.display_pending())report_screen();
#endif
  if(result && !display_result){
    edit_waiting=false;edit_feedback=result<0?2:edit_slot<2?3+edit_count:0;
    feedback_until=now+4000;
  }
  const bool expired=!edit_waiting && edit_slot>=0 && now>=feedback_until;
  if(expired){edit_slot=-1;edit_feedback=0;}
  if(result || updated || expired)refresh_edit();
  if(!moving && !down){
#ifdef STUDY_CARD_OVERLAYS
    if(open_card_light>=0 && ha_lights.take_detail(open_card_light) && paint_card_detail(open_card_light,page_pixels)){
      ++revision;blit(0,0,width,height,page_pixels);
    }
#endif
    bool list_changed=false;
    for(int i=0;i<light_count;i++)if(live_dirty[i]){
      live_dirty[i]=false;
      levels[i]=ha_lights.confirmed(i);
      list_changed=true;
      if(i==light_index() && light_sheet==LightSheet::closed){
        control_patch(page_pixels,detail_modes[levels[i]<0?0:levels[i]==0?1:2],detail_power_button);
        ++revision;
        paint_level(levels[i]);
      }
    }
    const int selected=light_index();
    if(selected>=0 && ha_lights.take_detail(selected) && light_sheet!=LightSheet::closed)draw_light_sheet(false);
    if(list_changed && lights_pixels){
      draw_light_list(lights_pixels);
      light_list_cached=true;
      scanout.invalidate_lamp();
      prepared_level=-2;
      if(current==lights
#ifdef STUDY_CARD_ART
         && !card_page_visible
#endif
      ){
        scanout.copy_pixels(page_pixels,lights_pixels,page_bytes);
        ++revision;blit(0,0,width,height,page_pixels);
      }
    }
    if(current==scenes && scene_matches()!=painted_scene
#ifdef STUDY_CARD_FIELDS
       && !card_page_visible
#endif
    ){
      scene_fields();++revision;blit(0,0,width,height,page_pixels);
    }
#ifdef STUDY_CARD_ART
    if(card_page_visible && card_page==CardPage::lights && card_lights_page.refresh(ha_lights)){++revision;blit(0,0,width,height,page_pixels);}
#ifdef STUDY_CARD_FIELDS
    if(card_page_visible && (current==home || current==scenes) && (card_page==CardPage::home || card_page==CardPage::scenes) &&
       paint_card_scene(card_theme,card_mode,card_page,page_pixels,false)){++revision;blit(0,0,width,height,page_pixels);}
#ifdef STUDY_CARD_CLIMATE
    if(card_page_visible && card_page==CardPage::climate && paint_card_climate(card_theme,card_mode,page_pixels,false)){
      ++revision;blit(0,0,width,height,page_pixels);
    }
#endif
#endif
#endif
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
// Keep the outer JPEG metadata separate from embedded EXIF thumbnails.
// IDF's fast info reader may see a thumbnail SOF before the primary SOF.
static size_t camera_bitstream(uint8_t *jpg,size_t size){
  if(size<4 || jpg[0]!=0xff || jpg[1]!=0xd8)return 0;
  size_t read=2,write=2;
  while(read+1<size && jpg[read]==0xff){
    const size_t start=read;
    while(read<size && jpg[read]==0xff)++read;
    if(read>=size)return 0;
    const auto marker=jpg[read++];
    if(marker==0xda){
      if(write!=start)memmove(jpg+write,jpg+start,size-start);
      return write+size-start;
    }
    if(read+2>size)return 0;
    const size_t len=(size_t(jpg[read])<<8)|jpg[read+1];
    if(len<2 || len>size-read)return 0;
    read+=len;
    if((marker<0xe0 || marker>0xef) && marker!=0xfe){
      if(write!=start)memmove(jpg+write,jpg+start,read-start);
      write+=read-start;
    }
  }
  return 0;
}
#ifdef STUDY_LIVE
// Ordinary JPEG artwork uses full-range YCbCr. The P4's RGB output applies
// video-range conversion, which clips shadows and oversaturates album covers.
// Decode packed V/U/Y and resize before quantizing to the display's RGB565.
static inline __attribute__((always_inline)) uint16_t jpeg_pixel(int v,int u,int luma,int x,int y){
  constexpr int bayer[4][4]={{0,8,2,10},{12,4,14,6},{3,11,1,9},{15,7,13,5}};
  v-=128;u-=128;
  const int red=std::clamp(luma+((359*v+128)>>8),0,255);
  const int green=std::clamp(luma-((88*u+183*v+128)>>8),0,255);
  const int blue=std::clamp(luma+((454*u+128)>>8),0,255);
  const int threshold=(2*bayer[y%4][x%4]+1)*255/32;
  return (((red*31+threshold)/255)<<11) | (((green*63+threshold)/255)<<5) | ((blue*31+threshold)/255);
}
static bool decode_artwork(const p4_runtime::AlbumClient::Frame &frame,
                           uint16_t *&pixels,int output_width,int output_height){
  if(!frame.data || !previous_pixels || !scratch || frame.size>page_bytes)return false;
  memcpy(scratch,frame.data,frame.size);
  const auto size=camera_bitstream(scratch,frame.size);
  jpeg_decode_picture_info_t info{};
  if(!size || jpeg_decoder_get_info(scratch,size,&info)!=ESP_OK || !info.width || !info.height)return false;
  const int mx=info.sample_method==JPEG_DOWN_SAMPLING_YUV420 || info.sample_method==JPEG_DOWN_SAMPLING_YUV422?16:8;
  const int stride=(info.width+mx-1)&~(mx-1);
  if(3ull*stride*((info.height+15)&~15u)>page_bytes)return false;
  jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_YUV444;
  uint32_t written=0;auto engine=decoder();
  if(!engine || jpeg_decoder_process(engine,&cfg,scratch,size,previous_pixels,page_bytes,&written)!=ESP_OK ||
     written<3u*stride*info.height)return false;
  if(!pixels)pixels=static_cast<uint16_t*>(heap_caps_malloc(2*output_width*output_height,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!pixels)return false;
  const int side=std::min(info.width,info.height);
  for(int y=0;y<output_height;++y){
    const int fy=std::clamp(((2*y+1)*side*128)/output_height-128,0,(side-1)*256);
    const int sy=(info.height-side)/2+(fy>>8),wy=fy&255;
    const auto *row=previous_pixels+3*(sy*stride+(info.width-side)/2);
    const auto *next=row+(sy+1<int(info.height)?3*stride:0);
    for(int x=0;x<output_width;++x){
      const int fx=std::clamp(((2*x+1)*side*128)/output_width-128,0,(side-1)*256);
      const int sx=fx>>8,wx=fx&255,right=std::min(sx+1,side-1);
      int yuv[3];
      for(int c=0;c<3;++c){
        const int top=row[3*sx+c]*(256-wx)+row[3*right+c]*wx;
        const int bottom=next[3*sx+c]*(256-wx)+next[3*right+c]*wx;
        yuv[c]=(top*(256-wy)+bottom*wy+32768)>>16;
      }
      pixels[y*output_width+x]=jpeg_pixel(yuv[0],yuv[1],yuv[2],x,y);
    }
  }
  return true;
}
static bool decode_library_thumbnail(const p4_runtime::AlbumClient::Frame &f,Thumbnail &out){
  return decode_artwork(f,out.pixels,thumbnail_side,thumbnail_side);
}
static void load_library_thumbnail(){
  if(!thumbnail_client.initialized())return;
  if(thumbnail_job>=0){
    p4_runtime::AlbumClient::Frame f;
    if(!thumbnail_client.take(f))return;
    auto &thumb=thumbnails[thumbnail_job];
    thumb.ready=f.version==thumbnail_client.generation() && decode_library_thumbnail(f,thumb);
    if(thumb.ready){player().dirty=true;ESP_LOGD("study","Music library thumbnail decoded");}
    heap_caps_free(f.data);thumbnail_job=-1;
  }
  int cols=library_steps[library_mode][0],step=library_steps[library_mode][1],viewport=library_list.h;
#ifdef STUDY_CARD_LIBRARY
  if(card_page_visible && library_open){
    const auto &l=library_layout();cols=l.cols;step=l.step;viewport=l.viewport.h;
  }
#endif
  for(size_t i=0;i<library.items.size();i++){
    const auto &url=library.items[i].thumbnail;
    const int y=int((library.first+i)/cols)*step-library_scroll;
    if(url.empty() || url.size()>=1536 || y>=viewport || y+step<=0)continue;
    if(std::any_of(thumbnails,thumbnails+thumbnail_slots,[&](const Thumbnail &t){return t.url==url;}))continue;
    auto *slot=std::min_element(thumbnails,thumbnails+thumbnail_slots,[](const Thumbnail &a,const Thumbnail &b){return a.used<b.used;});
    slot->url=url;slot->ready=false;slot->used=++thumbnail_stamp;thumbnail_job=slot-thumbnails;
    thumbnail_client.select("",url);return;
  }
}
static void update_cover(){
  const bool previously=cover_ready;
  bool changed=false;
  if(cover_generation!=album_client.generation()){
    cover_generation=album_client.generation();
    cover_ready=cover_speaker==selected_speaker && cover_picture==player().picture;
  }
  p4_runtime::AlbumClient::Frame f;
  if(album_client.take(f)){
    if(f.version==cover_generation && decode_artwork(f,cover_pixels,album_rect.w,album_rect.h)){
      cover_speaker=selected_speaker;cover_picture=player().picture;
      cover_ready=true;changed=true;ESP_LOGD("study","Album artwork decoded");
    }
    heap_caps_free(f.data);
  }
  if((!changed && previously==cover_ready) || (current!=home && current!=media) || speakers_open || library_open)return;
#ifdef STUDY_CARD_OVERLAYS
  if(card_page_visible && (queue_open || volume_open || card_page==CardPage::home)){
    player().dirty=true;return;
  }
#endif
  if(queue_open)return;
  if(volume_open){
    transport_fields();++revision;blit(0,0,width,height,page_pixels);return;
  }
#ifdef STUDY_CARD_FIELDS
  if(card_page_visible){
#ifdef STUDY_CARD_PLAYER
    if(card_page==CardPage::media)show_card_player(card_theme,card_mode);
#endif
    return;
  }
#endif
  show(current,0);
}
#endif
#ifdef STUDY_LIVE
static bool IRAM_ATTR __attribute__((optimize("O3"))) present_camera_pixels(const uint16_t *pixels,int source_w,int source_h,int stride){
  const Rect &v=
#ifdef STUDY_CARD_BELL
    card_bell_active?bell_view().video:
#endif
    bell_viewport;
  const int w=std::max(1,std::min(v.w,v.h*source_w/source_h));
  const int h=std::max(1,std::min(v.h,v.w*source_h/source_w));
  if(w!=bell_draw_w || h!=bell_draw_h){
#ifdef STUDY_CARD_BELL
    if(card_bell_active){
      if(!apply_player_patch(bell_view().empty,page_pixels,card_bell_file))return false;
    }else
#endif
      text_background(page_pixels,width,scratch,v,bell_empty_video[0],bell_empty_video[1]);
    bell_draw_w=w;bell_draw_h=h;
    ESP_LOGD("study","Camera image %dx%d at %d,%d size %dx%d",source_w,source_h,
             v.x+(v.w-w)/2,v.y+(v.h-h)/2,w,h);
  }
  const int left=(v.w-w)/2,top=(v.h-h)/2;
  for(int y=0;y<h;y++){
    const int edge=std::min(top+y,v.h-1-(top+y));
    int inset=0;
    if(edge<16){
      const float dy=15.5f-edge;
      inset=std::max(0,int(std::ceil(15.5f-std::sqrt(256.f-dy*dy))));
    }
    const auto *src=pixels+(y*source_h/h)*stride;
    auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(v.y+top+y)*width+v.x+left;
    for(int x=std::max(0,inset-left);x<std::min(w,v.w-inset-left);x++)dst[x]=src[x*source_w/w];
  }
  auto *first=page_pixels+2*(v.y*width+v.x);
  const bool presented=blit(v.x,v.y,v.w,v.h,first,width);
#ifdef STUDY_BENCH_TEST
  if(presented){
    uint32_t crc=0;
    for(int y=0;y<v.h;y++)crc=esp_rom_crc32_le(crc,first+2*y*width,2*v.w);
    ESP_LOGI("study","QA_VIDEO_FRAME %08x",crc);
  }
#endif
  return presented;
}
#endif
static bool IRAM_ATTR __attribute__((optimize("O3"))) draw_jpeg(const uint8_t *data,size_t size) {
  if(!scratch || current!=doorbell || !size || size>384*1024)return false;
  auto engine=decoder();
  if(!engine || !previous_pixels)return false;
  if(data!=scratch)memcpy(scratch,data,size);
  size=camera_bitstream(scratch,size);
  if(!size)return false;
  jpeg_decode_picture_info_t info{};
  const auto info_error=jpeg_decoder_get_info(scratch,size,&info);
  if(info_error!=ESP_OK || !info.width || !info.height ||
     info.width>1920 || info.height>1920 || info.width*info.height>1920*1080){
    static bool warned;
    if(!warned){ESP_LOGW("study","Camera header %s (%u x %u)",esp_err_to_name(info_error),info.width,info.height);warned=true;}
    return false;
  }
  jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_RGB565;
  cfg.rgb_order=panel_jpeg_order;
  uint32_t written=0;
  const bool exact=info.width==640 && info.height==400;
  const unsigned mx=info.sample_method==JPEG_DOWN_SAMPLING_YUV420 || info.sample_method==JPEG_DOWN_SAMPLING_YUV422?16:8;
  const unsigned my=info.sample_method==JPEG_DOWN_SAMPLING_YUV420?16:8;
  const unsigned stride=(info.width+mx-1)&~(mx-1);
  const size_t pixel_count=stride*((info.height+my-1)&~(my-1));
  bool full_range=false;
#ifdef STUDY_LIVE
  full_range=pulled_video && 3*pixel_count<=page_bytes;
  if(full_range)cfg.output_format=JPEG_DECODE_OUT_FORMAT_YUV444;
#endif
  const size_t need=(full_range?3:2)*pixel_count;
  size_t capacity=page_bytes;
  uint8_t *decoded=previous_pixels;
  uint8_t *output=exact?previous_pixels:scratch;
  bool allocated=false;
  if(!exact && (!decoded || need>capacity)){
    jpeg_decode_memory_alloc_cfg_t alloc{};alloc.buffer_direction=JPEG_DEC_ALLOC_OUTPUT_BUFFER;
    decoded=(uint8_t*)jpeg_alloc_decoder_mem(need,&alloc,&capacity);allocated=true;
  }
  if(!decoded)return false;
  const auto err=jpeg_decoder_process(engine,&cfg,scratch,size,decoded,std::min(need,capacity),&written);
  const bool ok=err==ESP_OK && written==need;
  if(!ok){
    static bool warned;
    if(!warned){ESP_LOGW("study","Camera decoder %s %ux%u mode %d produced %u of %u bytes",esp_err_to_name(err),info.width,info.height,int(info.sample_method),unsigned(written),unsigned(need));warned=true;}
  }
#ifdef STUDY_LIVE
  if(ok && pulled_video && page_pixels){
    if(full_range){
      // Forward conversion safely shrinks three-byte V/U/Y pixels in place.
      auto *pixels=reinterpret_cast<uint16_t*>(decoded);
      for(unsigned y=0;y<info.height;++y)for(unsigned x=0;x<stride;++x){
        const size_t i=y*stride+x;
        pixels[i]=jpeg_pixel(decoded[3*i],decoded[3*i+1],decoded[3*i+2],x,y);
      }
    }
    const bool presented=present_camera_pixels(reinterpret_cast<const uint16_t*>(decoded),info.width,info.height,stride);
    if(allocated)free(decoded);
    return presented;
  }
#endif
  if(ok && !exact){
    const unsigned w=std::min<uint32_t>(640,400*info.width/info.height);
    const unsigned h=std::min<uint32_t>(400,640*info.height/info.width);
    memset(output,0,640*400*2);
    for(unsigned y=0;y<h;y++){
      const auto *src=reinterpret_cast<const uint16_t*>(decoded)+y*info.height/h*stride;
      auto *dst=reinterpret_cast<uint16_t*>(output)+((400-h)/2+y)*640+(640-w)/2;
      for(unsigned x=0;x<w;x++)dst[x]=src[x*info.width/w];
    }
  }
  if(allocated)free(decoded);
  if(!ok)return false;
  if(page_pixels)for(int y=0;y<400;y++)memcpy(page_pixels+2*((video_y+y)*width+40),output+2*y*640,1280);
  bool presented=blit(40,video_y,640,400,output);
#ifdef STUDY_BENCH_TEST
  if(presented)ESP_LOGI("study","QA_VIDEO_FRAME %08x",esp_rom_crc32_le(0,output,640*400*2));
#endif
  return presented;
}
static bool frame(const std::string &encoded) {
  if(!scratch || current!=doorbell || encoded.empty() || encoded.size()>60000)return false;
  size_t bytes=0;
  if(mbedtls_base64_decode(scratch,45000,&bytes,reinterpret_cast<const unsigned char*>(encoded.data()),encoded.size())!=0)return false;
  return draw_jpeg(scratch,bytes);
}
#ifdef STUDY_LIVE
inline void present_bell_video(){
  int result=bell_client.present(draw_jpeg);
  if(current!=doorbell){pulled_video=false;return;}
  if(!pulled_video || !result)return;
  paint_bell_status(result>0?1:2);
  if(result>0 && (++bell_frames==1 || bell_frames%24==0))
    ESP_LOGI("study","Doorbell video presented %u frames",bell_frames);
}
#endif
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
