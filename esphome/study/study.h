#pragma once
#include "study_assets.h"
#if __has_include("live_runtime/study_profile.h")
#define STUDY_LIVE
#include "control_art.h"
#include "media_art.h"
#include "text_renderer.h"
#include "live_runtime/study_profile.h"
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
static uint16_t *cover_pixels=nullptr;
static bool cover_ready=false;
static bool mini_art_enabled=default_mini_art;
#ifdef STUDY_BENCH_TEST
static constexpr const char *display_namespace="p4_qa_display";
#else
static constexpr const char *display_namespace="p4_display";
#endif
static void load_display_choice(){
  nvs_handle_t h;
  if(nvs_open(display_namespace,NVS_READONLY,&h)!=ESP_OK)return;
  uint8_t value=0;if(nvs_get_u8(h,"mini",&value)==ESP_OK)mini_art_enabled=value!=0;
  nvs_close(h);
}
static bool save_display_choice(bool enabled){
  nvs_handle_t h;if(nvs_open(display_namespace,NVS_READWRITE,&h)!=ESP_OK)return false;
  const bool ok=nvs_set_u8(h,"mini",enabled)==ESP_OK && nvs_commit(h)==ESP_OK;nvs_close(h);
  if(ok)mini_art_enabled=enabled;
  return ok;
}
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
  const int pct=volume_drag>=0?volume_drag:std::max(0,player.volume);
  volume_paint(volume_button,volume_button_tiles[pct]);
  if(volume_open)volume_paint(volume_popup,volume_popup_tiles[pct]);
}
static void label(const TextArea &field,const char *value){text_field(page_pixels,width,scratch,field,value);}
static void playback_time(const TextArea &area,int seconds){
  char out[24];snprintf(out,sizeof(out),"%d:%02d",seconds/60,seconds%60);label(area,out);
}
static void progress_fields(){
  const int pos=seek_drag>=0?seek_drag:int(std::lround(player.position())),duration=player.duration;
  playback_time(elapsed_time,pos);playback_time(total_time,duration);
  const auto &r=seek_slider;
  const int end=duration?std::clamp(int(std::lround(double(pos)*r.w/duration)),0,r.w):0;
  text_background(page_pixels,width,scratch,seek_background,seek_art[0][0],seek_art[0][1]);
  const int n=player.playing?44:1,phase=player.playing?clock_ms()*44/2800%44:0;
  const auto &fill=seek_art[player.playing?2:1];
  if(end && tinfl_decompress_mem_to_mem(scratch,2*n*r.h,text_art+fill[0],fill[1],1)==size_t(2*n*r.h)){
    for(int y=0;y<r.h;y++){
      auto *dst=reinterpret_cast<uint16_t*>(page_pixels)+(r.y+y)*width+r.x;
      auto *src=reinterpret_cast<const uint16_t*>(scratch)+y*n;
      for(int x=0;x<end;x++)dst[x]=src[(x+phase)%n];
    }
  }
  const Rect thumb{r.x+end-5,r.y+r.h/2-4,10,10};
  text_background(page_pixels,width,scratch,thumb,seek_art[3][0],seek_art[3][1]);
}
static void home_player(){
  const bool cover=cover_ready && mini_art_enabled;
  const auto &art=home_strip_art[player.playing?(cover?2:1):0];
  text_background(page_pixels,width,scratch,home_strip,art[0],art[1]);
  if(player.playing){
    if(cover)draw_cover(mini_album_rect);
    label(cover?home_cover_title:home_title,player.title.empty()?"Music":player.title.c_str());
    label(cover?home_cover_artist:home_artist,player.title.empty()?"Nothing playing":player.artist.empty()?"Playing":player.artist.c_str());
  }
}
static void status_fields(){
  if(current==settings_page)label(mini_choice,mini_art_enabled?"On":"Off");
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
    label(ha_status,ha_lights.receiving()?"• connected":"• disconnected");
    label(net_status,esphome::network::is_connected()?"Ethernet":"Disconnected");
    label(backlight_status,applied_brightness>=0?"• running":"• unavailable");
    const auto minutes=clock_ms()/60000;
    char uptime[32];
    if(minutes>=60)snprintf(uptime,sizeof(uptime),"%lldh %lldm",minutes/60,minutes%60);
    else snprintf(uptime,sizeof(uptime),"%lldm",minutes);
    label(up_status,uptime);
  }
}
static void transport_fields(){
  if(queue_open){
    const auto &list=player.playlist.empty()?player.album:player.playlist;
    const int mask=int(!player.title.empty())+2*int(!list.empty());
    text_background(page_pixels,width,scratch,queue_patches[0],queue_pages[0][0],queue_pages[0][1]);
    if(mask)text_background(page_pixels,width,scratch,queue_patches[mask],queue_pages[mask][0],queue_pages[mask][1]);
    if(mask&1){
      std::string track=player.title;
      if(!player.artist.empty())track+="  ·  "+player.artist;
      label(queue_track,track.c_str());
    }
    if(mask&2)label(mask==2?queue_playlist_2:queue_playlist_3,("Playlist: "+list).c_str());
    return;
  }
  label(song_title,player.title.empty()?"Nothing playing":player.title.c_str());
  draw_cover(album_rect);
  label(song_artist,player.title.empty()?"Browse your music library":player.artist.empty()?initial_speaker_name:player.artist.c_str());
  progress_fields();
  control_patch(page_pixels,shuffle_modes[player.shuffled],transport_buttons[0]);
  control_patch(page_pixels,play_modes[player.playing],transport_buttons[2]);
  control_patch(page_pixels,repeat_modes[player.repeat_mode],transport_buttons[4]);
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
#ifdef STUDY_LIVE
  light_sheet=LightSheet::closed;sheet_drag=-1;
  volume_open=false;queue_open=false;volume_drag=-1;seek_drag=-1;
  if(change && current==doorbell)bell_client.close();
#endif
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
      && dest!=room_menu_page && dest!=settings_page && dest!=diagnostics_page
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
    if(dest==home)home_player();
    status_fields();
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
  load_display_choice();
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
#endif
static void touch(int x,int y) {
  bench_demo=false;
#ifdef STUDY_LIVE
  last_activity=clock_ms();
  if(wake_touch)return;
  if(current==idle){
    wake_touch=true;blanked=false;show(wake_page,0);apply_brightness();return;
  }
  if(!moving && sheet_touch(x,y))return;
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
  if(!down && current==home && player.playing && home_strip.contains(x,y)){
    down=true;pressed=home_play.contains(x,y)?-151:-152;x0=x;y0=y;dx=dy=0;return;
  }
  if(pressed==-151 || pressed==-152){dx=x-x0;dy=y-y0;return;}
  if(!volume_open && current==media && !moving &&
     (seek_drag>=0 || (!down && player.available && player.can_seek && player.duration && seek_slider.contains(x,y)))){
    down=true;pressed=-2;seek_drag=std::clamp(int(std::lround(double(x-seek_slider.x)*player.duration/seek_slider.w)),0,player.duration);
    progress_fields();++revision;blit(0,0,width,height,page_pixels);return;
  }
  if(current==media && !moving && (volume_open || (!down && volume_button.contains(x,y)) || pressed==-150)){
    if(!down){
      down=true;x0=x;y0=y;pressed=-150;
      if(volume_open && volume_slider.contains(x,y))volume_drag=std::max(0,player.volume);
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
  if(sheet_release())return;
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
    player.seek(seek_drag);seek_drag=-1;down=false;pressed=-2;return;
  }
  if(pressed==-151 || pressed==-152){
    const bool toggle=pressed==-151;down=false;pressed=-2;
    if(std::abs(dx)<40 && std::abs(dy)<40){
      if(toggle)player.press(p4_runtime::MediaClient::play_pause);else go(media);
    }
    dx=dy=0;return;
  }
  if(current==media && pressed==-150){
    down=false;pressed=-2;
    if(volume_drag>=0){player.set_volume(volume_drag);volume_drag=-1;}
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
#ifdef STUDY_LIVE
static int bell_status=-1;
static bool pulled_video=false;
static unsigned bell_frames=0;
static int bell_draw_w=0,bell_draw_h=0;
static void paint_bell_status(int next){
  if(next==bell_status)return;
  bell_status=next;
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
  if(bell_enabled){
    bell_client.listen();
    const bool test=bell_client.test_ring.exchange(false);
    if(test || bell_client.trigger_ring){bell_client.trigger_ring=false;camera_ring(test);}
  }
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
  if(!moving && !down && current!=doorbell && !bench_demo)update_cover();
  player.tick();
  if(player.dirty && !moving && !down){
    player.dirty=false;
    if(current==media && page_pixels){transport_fields();++revision;blit(0,0,width,height,page_pixels);}
    if(current==home && page_pixels){home_player();++revision;blit(0,0,width,height,page_pixels);}
  }
  static int64_t next_progress=0;
  if(current==media && player.playing && player.duration && !down && !moving && !volume_open && !queue_open && now>=next_progress){
    progress_fields();++revision;blit(0,0,width,height,page_pixels);next_progress=now+125;
  }
  static int64_t next_status=0;
  if(!down && !moving && page_pixels && (current==room_menu_page || current==diagnostics_page) && now>=next_status){
    status_fields();next_status=now+5000;++revision;blit(0,0,width,height,page_pixels);
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
static void update_cover(){
  const bool previously=cover_ready;
  bool changed=false;
  if(cover_generation!=album_client.generation()){
    cover_generation=album_client.generation();cover_ready=false;
  }
  p4_runtime::AlbumClient::Frame f;
  if(album_client.take(f)){
    if(f.version==cover_generation && f.data && previous_pixels && scratch){
      memcpy(scratch,f.data,f.size);
      const auto bytes=camera_bitstream(scratch,f.size);
      jpeg_decode_picture_info_t info{};
      if(bytes && jpeg_decoder_get_info(scratch,bytes,&info)==ESP_OK && info.width && info.height &&
         info.width<=1280 && info.height<=1280){
        auto engine=decoder();jpeg_decode_cfg_t cfg{};cfg.output_format=JPEG_DECODE_OUT_FORMAT_RGB565;cfg.rgb_order=panel_jpeg_order;
        const int mx=(info.sample_method==JPEG_DOWN_SAMPLING_YUV420 || info.sample_method==JPEG_DOWN_SAMPLING_YUV422)?16:8;
        const int stride=(info.width+mx-1)&~(mx-1);
        uint32_t written=0;
        if(engine && 2u*stride*((info.height+15)&~15u)<=page_bytes &&
           jpeg_decoder_process(engine,&cfg,scratch,bytes,previous_pixels,page_bytes,&written)==ESP_OK &&
           written>=2u*stride*info.height){
          if(!cover_pixels)cover_pixels=static_cast<uint16_t*>(heap_caps_malloc(2*album_rect.w*album_rect.h,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
          if(cover_pixels){
            const int side=std::min(info.width,info.height);
            const auto *src=reinterpret_cast<const uint16_t*>(previous_pixels);
            for(int y=0;y<album_rect.h;y++){
              const auto *row=src+((info.height-side)/2+y*side/album_rect.h)*stride+(info.width-side)/2;
              for(int x=0;x<album_rect.w;x++)cover_pixels[y*album_rect.w+x]=row[x*side/album_rect.w];
            }
            cover_ready=true;changed=true;ESP_LOGD("study","Album artwork decoded %ux%u",info.width,info.height);
          }
        }
      }
    }
    heap_caps_free(f.data);
  }
  if((!changed && previously==cover_ready) || (current!=home && current!=media) || volume_open || queue_open)return;
  show(current,0);
}
#endif
#ifdef STUDY_LIVE
static bool present_camera_pixels(const uint16_t *pixels,int source_w,int source_h,int stride){
  const Rect &v=bell_viewport;
  const int w=std::max(1,std::min(v.w,v.h*source_w/source_h));
  const int h=std::max(1,std::min(v.h,v.w*source_h/source_w));
  if(w!=bell_draw_w || h!=bell_draw_h){
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
static bool draw_jpeg(const uint8_t *data,size_t size) {
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
  const size_t need=2*stride*((info.height+my-1)&~(my-1));
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
