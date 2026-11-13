#pragma once
#include "fleet_client.h"
#include <esp_heap_caps.h>
#include <array>
#include <cstring>

namespace p4_runtime {
class DoorbellClient {
 public:
  using Draw=bool (*)(const uint8_t*,size_t);
  std::atomic<bool> test_ring{false};
  bool trigger_ring=false;
  static constexpr size_t frame_limit=384*1024;
  void begin(FleetSettings settings,const char *trigger,const char *camera,const char *origin){
    settings_=settings;
    camera_=camera;origin_=origin;
    ticket_=xQueueCreate(1,sizeof(Ticket));
    if(*camera && *origin && ticket_)
      esphome::api::global_api_server->subscribe_home_assistant_state(camera,"entity_picture",[this](esphome::StringRef state){
        const auto path=state.str();
        const std::string prefix="/api/camera_proxy/"+std::string(camera_)+"?token=";
        Ticket ticket{};
        if(path.compare(0,prefix.size(),prefix)==0){
          const auto token=path.substr(prefix.size());
          if(!token.empty() && token.size()<sizeof(ticket.value) &&
             token.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")==std::string::npos)
            memcpy(ticket.value,token.data(),token.size());
        }
        xQueueOverwrite(ticket_,&ticket);
        ESP_LOGD("study","Camera playback permission %s",*ticket.value?"received":"unavailable");
      });
    if(*trigger){
      binary_=strncmp(trigger,"binary_sensor.",14)==0;
      esphome::api::global_api_server->subscribe_home_assistant_state(trigger,nullptr,[this](esphome::StringRef state){
        auto next=state.str();
        if(next.empty() || next=="unavailable" || next=="unknown"){previous_.clear();return;}
        const bool timestamp=next.size()>=19 && next[4]=='-' && next[7]=='-' &&
            (next[10]=='T' || next[10]==' ') && next[13]==':' && next[16]==':';
        trigger_ring|=!previous_.empty() && next!=previous_ &&
                      (binary_?(previous_=="off" && next=="on"):timestamp);
        previous_=next;
      });
    }
  }
  void listen(){
    if(!settings_.url || listener_ || !esphome::network::is_connected())return;
    xTaskCreate([](void *self){static_cast<DoorbellClient*>(self)->wait_loop();},
                "bell_wait",6144,this,1,&listener_);
  }
  bool reserve_frames(){
    if(!free_)free_=xQueueCreate(2,sizeof(Frame));
    if(!ready_)ready_=xQueueCreate(2,sizeof(Frame));
    if(!free_ || !ready_)return false;
    for(auto &slot:slots_)if(!slot){
      slot=static_cast<uint8_t*>(heap_caps_malloc(frame_limit,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!slot)return false;
      Frame frame{slot,0,0};xQueueSend(free_,&frame,0);
    }
    return true;
  }
  void open(bool use_server){
    prefer_server_=use_server;
    if(!worker_){
      if(!reserve_frames()){failed_=true;ESP_LOGW("study","Camera frame buffers unavailable");return;}
      xTaskCreate([](void *self){static_cast<DoorbellClient*>(self)->stream_loop();},
                  "bell_stream",8192,this,1,&worker_);
    }
    ++generation_;running_=true;failed_=false;
    if(worker_)xTaskNotifyGive(worker_);else failed_=true;
  }
  void close(){running_=false;++generation_;failed_=false;}
  int present(Draw draw){
    Frame frame;
    if(ready_ && xQueueReceive(ready_,&frame,0)==pdTRUE){
      const bool current=running_ && generation_==frame.generation;
      const bool ok=current && draw(frame.pixels,frame.size);
      xQueueSend(free_,&frame,0);
      if(current)return ok?1:-1;
    }
    return failed_.exchange(false)?-1:0;
  }
 private:
  struct Frame {uint8_t *pixels;size_t size;uint32_t generation;};
  struct Ticket {char value[160];};
  struct Request {
    esp_http_client_handle_t handle;
    Request(const FleetSettings &s,const char *path,int timeout):
      Request(std::string(s.url)+"/api/panel/"+s.id+"/doorbell/"+path,timeout,s.token){}
    Request(const std::string &url,int timeout,const char *token=nullptr){
      esp_http_client_config_t cfg{};
      cfg.url=url.c_str();cfg.timeout_ms=timeout;cfg.disable_auto_redirect=true;
      cfg.crt_bundle_attach=esp_crt_bundle_attach;
      handle=esp_http_client_init(&cfg);
      if(handle && token)esp_http_client_set_header(handle,"X-Panel-Token",token);
    }
    ~Request(){if(handle)esp_http_client_cleanup(handle);}
    int start(){
      if(!handle || esp_http_client_open(handle,0)!=ESP_OK || esp_http_client_fetch_headers(handle)<0)return 0;
      return esp_http_client_get_status_code(handle);
    }
    bool read(uint8_t *out,size_t size){
      while(size){
        int n=esp_http_client_read(handle,reinterpret_cast<char*>(out),size);
        if(n<=0)return false;
        out+=n;size-=n;
      }
      return true;
    }
  };
  FleetSettings settings_{};
  const char *camera_="",*origin_="";
  TaskHandle_t listener_{},worker_{};
  QueueHandle_t ready_{},free_{},ticket_{};
  std::array<uint8_t*,2> slots_{};
  std::atomic<uint32_t> generation_{0};
  std::atomic<bool> running_{false},failed_{false},prefer_server_{true};
  std::string previous_;
  bool binary_=false;
  // HA's MJPEG response contains a length for each JPEG. Read headers and
  // payload from the same buffered stream so a TCP split never loses bytes.
  struct Parts{
    esp_http_client_handle_t h;
    uint8_t buffer[1536];size_t pos=0,n=0;
    bool fill(){
      if(pos<n)return true;
      const int got=esp_http_client_read(h,reinterpret_cast<char*>(buffer),sizeof(buffer));
      pos=0;n=got>0?got:0;return n>0;
    }
    bool line(char *out,size_t capacity){
      size_t len=0;
      while(fill()){
        const char c=buffer[pos++];
        if(c=='\n'){out[len]=0;return true;}
        if(c!='\r'){if(len+1>=capacity)return false;out[len++]=c;}
      }
      return false;
    }
    bool next(Frame &frame){
      char header[384];size_t bytes=0;
      bool boundary=false;
      for(int i=0;i<24;i++){
        if(!line(header,sizeof(header)))return false;
        if(!boundary){boundary=!strncmp(header,"--",2);continue;}
        if(!*header)break;
        if(!strncasecmp(header,"Content-Length:",15)){
          char *end=nullptr;bytes=strtoul(header+15,&end,10);
          if(!end || *end || bytes>frame_limit)return false;
        }
      }
      if(!bytes)return false;
      frame.size=bytes;
      for(size_t used=0;used<bytes;){
        if(!fill())return false;
        size_t take=std::min(bytes-used,n-pos);
        memcpy(frame.pixels+used,buffer+pos,take);pos+=take;used+=take;
      }
      return true;
    }
  };
  void direct_stream(uint32_t session){
    Ticket t{};
    if(!ticket_ || xQueuePeek(ticket_,&t,0)!=pdTRUE || !*t.value){
      ESP_LOGW("study","Direct camera is waiting for its Home Assistant subscription");return;
    }
    const std::string url=std::string(origin_)+"/api/camera_proxy_stream/"+camera_+"?token="+t.value;
    Request req(url,6000);
    const int status=req.start();
    ESP_LOGI("study","Direct camera HTTP status %d",status);
    if(status!=200)return;
    Parts parts{req.handle};
    bool first=true;
    while(running_ && generation_==session){
      Frame f;
      if(xQueueReceive(free_,&f,pdMS_TO_TICKS(50))!=pdTRUE)continue;
      if(!parts.next(f)){xQueueSend(free_,&f,0);ESP_LOGW("study","Direct camera multipart frame ended");break;}
      if(first){ESP_LOGI("study","Direct camera received %u bytes",unsigned(f.size));first=false;}
      f.generation=session;xQueueSend(ready_,&f,0);
    }
  }
  void wait_loop(){
    for(;;){
      int status;
      {
        Request r(settings_,"wait",19000);
        status=r.start();
        uint8_t answer[4];
        if(status==200 && r.read(answer,sizeof(answer)) && !memcmp(answer,"ring",4))test_ring=true;
      }
      vTaskDelay(pdMS_TO_TICKS(status==200 || status==204?150:10000));
    }
  }
  void stream_loop(){
    for(;;){
      ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
      if(!running_)continue;
      const auto session=generation_.load();
      Request r(settings_,"video",9000);
      if(prefer_server_ && r.start()==200){
        while(running_ && generation_==session){
          Frame f;
          if(xQueueReceive(free_,&f,pdMS_TO_TICKS(50))!=pdTRUE)continue;
          uint8_t length[4];
          bool ok=r.read(length,4);
          f.size=ok?(uint32_t(length[0])<<24 | uint32_t(length[1])<<16 |
                     uint32_t(length[2])<<8 | length[3]):0;
          if(!f.size || f.size>45000 || !r.read(f.pixels,f.size)){
            xQueueSend(free_,&f,0);break;
          }
          f.generation=session;
          xQueueSend(ready_,&f,0);
        }
      }
      if(running_ && generation_==session)direct_stream(session);
      if(running_ && generation_==session)failed_=true;
    }
  }
};
}
