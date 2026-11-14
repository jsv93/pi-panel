#if defined(USE_ESP32_HOSTED) && defined(STUDY_RENDER_NETWORK) && !defined(STUDY_NETWORK_SCREEN_DEFINED)
#define STUDY_NETWORK_SCREEN_DEFINED
#include "wifi_client.h"
namespace study {
using Wifi=p4_runtime::WifiClient;
static Wifi station;
static Wifi::Result wifi_result;
static bool network_open=false;
static int wifi_selected=-1,wifi_scroll=0,wifi_touch_scroll=0;
static bool wifi_shift=false,wifi_pending=false;
static bool wifi_scan_after_restore=false;
static char passphrase[64]{};
static std::string wifi_password_preview(){
  std::string display;
  const size_t n=strlen(passphrase);
  for(size_t i=1;i<n;++i)display+="•";
  if(n)display+=passphrase[n-1];
  return display;
}
#ifdef STUDY_CARD_WIFI
static const WifiLayout &wifi_layout(){return card_wifi_layouts[selected_theme*6+card_mode];}
static const WifiSheet &wifi_sheet(){
  const auto &l=wifi_layout();
  return card_wifi_sheets[l.start+std::min(int(wifi_result.networks.size()),l.count-1)];
}
#endif
static Rect wifi_first_row(){
#ifdef STUDY_CARD_WIFI
  if(card_network_open){const auto &l=wifi_layout();auto r=l.row;r.y+=wifi_sheet().top-l.top;return r;}
#endif
  return wifi_rows[0];
}
static int wifi_row_step(){
#ifdef STUDY_CARD_WIFI
  if(card_network_open)return wifi_layout().step;
#endif
  return wifi_rows[1].y-wifi_rows[0].y;
}
static int wifi_list_bottom(){
#ifdef STUDY_CARD_WIFI
  if(card_network_open)return height;
#endif
  return std::min(1210,height);
}
static int wifi_scroll_limit(){
#ifdef STUDY_CARD_WIFI
  if(card_network_open){
    const auto row=wifi_first_row();
    const int n=wifi_result.networks.size();
    return n?std::max(0,row.y+(n-1)*wifi_row_step()+row.h+34-height):0;
  }
#endif
  return std::max(0,int(wifi_result.networks.size())*wifi_row_step()-wifi_list_bottom()+wifi_first_row().y);
}
static void close_network(){
  network_open=false;wifi_selected=-1;wifi_shift=false;wifi_pending=false;wifi_scan_after_restore=false;
#ifdef STUDY_CARD_WIFI
  card_network_open=false;
#endif
  explicit_bzero(passphrase,sizeof(passphrase));
}
static void paint_network(){
#ifdef STUDY_OVERLAY_PALETTES
  TextPaletteScope colours(palette.selection());
#endif
#ifdef STUDY_CARD_WIFI
  if(card_network_open){
    if(paint_card_network()){++revision;blit(0,0,width,height,page_pixels);return;}
    card_network_open=false;
    wifi_scroll=0;
  }
#endif
  const bool join=wifi_selected>=0 && size_t(wifi_selected)<wifi_result.networks.size();
  const auto *base=join?wifi_keyboard[wifi_shift]:wifi_empty;
  text_background(page_pixels,width,scratch,{0,0,width,height},base[0],base[1]);
  std::string connection="not connected";
  if(wifi_result.ssid[0])connection=std::string(wifi_result.ssid)+" · "+std::to_string(wifi_result.signal)+"%";
  text_field(page_pixels,width,scratch,wifi_now,connection.c_str(),0,height,false);
  if(join){
    const auto &net=wifi_result.networks[wifi_selected];
    const char *message=wifi_result.state==Wifi::State::joining?"Connecting…":wifi_result.state==Wifi::State::failed?"Failed":net.secure?"":"open network";
    text_field(page_pixels,width,scratch,wifi_join_name,net.ssid,0,height,false);
    text_field(page_pixels,width,scratch,wifi_message,message,0,height,false);
    text_field(page_pixels,width,scratch,wifi_password,wifi_password_preview().c_str(),0,height,false);
  }else{
    const auto &r=wifi_rows[0];
    for(size_t i=0;i<wifi_result.networks.size();i++){
      const int y=r.y+int(i)*wifi_row_step()-wifi_scroll;
      if(y+r.h<=r.y || y>=wifi_list_bottom())continue;
      const auto &net=wifi_result.networks[i];const auto *art=wifi_row_art[net.secure?0:1];
      auto name=wifi_name,signal=wifi_signal;
      bool rendered=false;
#ifdef STUDY_OVERLAY_WIFI
      const auto *row=overlay_artwork.wifi(text_palette,!strcmp(net.ssid,wifi_result.ssid),
                                          net.secure,net.signal,scratch,2*r.w*r.h);
      if(row){
        name.rect=row->name;signal.rect=row->signal;name.colour=row->colour;
        rendered=true;
      }
#endif
      if(!rendered && !text_image(scratch,2*r.w*r.h,art[0],art[1]))continue;
      for(int row=std::max(0,r.y-y);row<r.h && y+row<wifi_list_bottom();row++)
        memcpy(page_pixels+2*((y+row)*width+r.x),scratch+2*row*r.w,2*r.w);
      name.rect.y+=y-r.y;signal.rect.y+=y-r.y;
      text_field(page_pixels,width,scratch,name,net.ssid,r.y,wifi_list_bottom(),false);
      const char *bars=net.signal>=75?"▂▄▆█":net.signal>=50?"▂▄▆":net.signal>=25?"▂▄":"▂";
      char value[32];snprintf(value,sizeof(value),"%s %u%%",bars,unsigned(net.signal));
      text_field(page_pixels,width,scratch,signal,value,r.y,wifi_list_bottom(),false);
    }
    if(wifi_result.networks.empty()){
      auto note=wifi_now;note.rect.y=r.y;
      const char *message=wifi_result.state==Wifi::State::scanning?"Scanning…":wifi_result.state==Wifi::State::failed?"Wi-Fi unavailable":"No networks found";
      text_field(page_pixels,width,scratch,note,message,0,height,false);
    }
  }
  ++revision;blit(0,0,width,height,page_pixels);
}
static void network_refresh(){
  if(!network_open || !wifi_pending || down)return;
  auto next=station.snapshot();
  if(next.state==Wifi::State::joining || next.state==Wifi::State::scanning)return;
  if(wifi_scan_after_restore){
    wifi_scan_after_restore=false;
    wifi_pending=station.scan();wifi_result=station.snapshot();paint_network();return;
  }
  wifi_pending=false;wifi_result=std::move(next);
  if(wifi_result.state==Wifi::State::connected){wifi_selected=-1;explicit_bzero(passphrase,sizeof(passphrase));}
  paint_network();
}
static void network_action(int x,int y){
  if(!network_open){
    close_network();network_open=true;wifi_scroll=0;
#ifdef STUDY_CARD_WIFI
    card_network_open=selected_theme<2 && card_assets_ready();
#endif
    if(!station.scan())wifi_scan_after_restore=true;
    wifi_pending=true;
    wifi_result=station.snapshot();paint_network();return;
  }
  bool back=wifi_back.contains(x,y);
  Rect cancel=wifi_cancel,go=wifi_go;
#ifdef STUDY_CARD_WIFI
  if(card_network_open){
    const auto &l=wifi_layout();back=y<(wifi_selected<0?wifi_sheet().top:l.join_top);
    cancel=l.cancel;go=l.go;
  }
#endif
  if(back){close_network();show(settings_page,0);return;}
  if(wifi_selected<0){
    const auto row=wifi_first_row();
    const int index=(y-row.y+wifi_scroll)/wifi_row_step();
    int clip=row.y;
#ifdef STUDY_CARD_WIFI
    if(card_network_open)clip=std::max(wifi_sheet().top,row.y-wifi_scroll);
#endif
    if(y>=clip && y<wifi_list_bottom() && x>=row.x && x<row.x+row.w && (y-row.y+wifi_scroll)%wifi_row_step()<row.h &&
       index>=0 && size_t(index)<wifi_result.networks.size()){
      wifi_selected=index;wifi_shift=false;explicit_bzero(passphrase,sizeof(passphrase));paint_network();
    }
    return;
  }
  if(wifi_result.state==Wifi::State::joining)return;
  if(cancel.contains(x,y)){wifi_selected=-1;explicit_bzero(passphrase,sizeof(passphrase));paint_network();return;}
  if(go.contains(x,y)){
    const auto &net=wifi_result.networks[wifi_selected];
    wifi_pending=station.join(net.ssid,passphrase);
    wifi_result.state=wifi_pending?Wifi::State::joining:Wifi::State::failed;paint_network();return;
  }
  for(size_t i=0;i<sizeof(wifi_keys_0)/sizeof(wifi_keys_0[0]);i++){
    auto key=(wifi_shift?wifi_keys_1:wifi_keys_0)[i];
#ifdef STUDY_CARD_WIFI
    if(card_network_open)key=card_wifi_keys[selected_theme][i];
#endif
    if(!key.contains(x,y))continue;
    const auto *value=(wifi_shift?wifi_values_1:wifi_values_0)[i];
    const size_t len=strlen(passphrase);
    if(!strcmp(value,"__shift"))wifi_shift=!wifi_shift;
    else if(!strcmp(value,"__del")){if(len)passphrase[len-1]=0;}
    else if(len<sizeof(passphrase)-1)passphrase[len]=!strcmp(value,"__space")?' ':*value;
    paint_network();return;
  }
}
}
#endif
