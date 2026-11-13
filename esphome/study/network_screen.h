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
static char passphrase[64]{};
static int wifi_row_step(){return wifi_rows[1].y-wifi_rows[0].y;}
static int wifi_list_bottom(){return std::min(1210,height);}
static int wifi_scroll_limit(){return std::max(0,int(wifi_result.networks.size())*wifi_row_step()-wifi_list_bottom()+wifi_rows[0].y);}
static void close_network(){
  network_open=false;wifi_selected=-1;wifi_shift=false;wifi_pending=false;
  explicit_bzero(passphrase,sizeof(passphrase));
}
static void paint_network(){
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
    std::string masked;
    for(size_t i=0;i<strlen(passphrase);i++)masked+="•";
    text_field(page_pixels,width,scratch,wifi_password,masked.c_str(),0,height,false);
  }else{
    const auto &r=wifi_rows[0];
    for(size_t i=0;i<wifi_result.networks.size();i++){
      const int y=r.y+int(i)*wifi_row_step()-wifi_scroll;
      if(y+r.h<=r.y || y>=wifi_list_bottom())continue;
      const auto &net=wifi_result.networks[i];const auto *art=wifi_row_art[net.secure?0:1];
      if(tinfl_decompress_mem_to_mem(scratch,2*r.w*r.h,text_art+art[0],art[1],1)!=size_t(2*r.w*r.h))continue;
      for(int row=std::max(0,r.y-y);row<r.h && y+row<wifi_list_bottom();row++)
        memcpy(page_pixels+2*((y+row)*width+r.x),scratch+2*row*r.w,2*r.w);
      auto name=wifi_name,signal=wifi_signal;
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
  wifi_pending=false;wifi_result=std::move(next);
  if(wifi_result.state==Wifi::State::connected){wifi_selected=-1;explicit_bzero(passphrase,sizeof(passphrase));}
  paint_network();
}
static void network_action(int x,int y){
  if(!network_open){
    close_network();network_open=true;wifi_scroll=0;wifi_pending=station.scan();
    wifi_result=station.snapshot();paint_network();return;
  }
  if(wifi_back.contains(x,y)){close_network();show(settings_page,0);return;}
  if(wifi_selected<0){
    const int index=(y-wifi_rows[0].y+wifi_scroll)/wifi_row_step();
    if(y>=wifi_rows[0].y && y<wifi_list_bottom() && x>=wifi_rows[0].x && x<wifi_rows[0].x+wifi_rows[0].w &&
       index>=0 && size_t(index)<wifi_result.networks.size()){
      wifi_selected=index;wifi_shift=false;explicit_bzero(passphrase,sizeof(passphrase));paint_network();
    }
    return;
  }
  if(wifi_result.state==Wifi::State::joining)return;
  if(wifi_cancel.contains(x,y)){wifi_selected=-1;explicit_bzero(passphrase,sizeof(passphrase));paint_network();return;}
  if(wifi_go.contains(x,y)){
    const auto &net=wifi_result.networks[wifi_selected];
    wifi_pending=station.join(net.ssid,passphrase);
    wifi_result.state=wifi_pending?Wifi::State::joining:Wifi::State::failed;paint_network();return;
  }
  for(size_t i=0;i<sizeof(wifi_keys_0)/sizeof(wifi_keys_0[0]);i++){
    if(!(wifi_shift?wifi_keys_1:wifi_keys_0)[i].contains(x,y))continue;
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
