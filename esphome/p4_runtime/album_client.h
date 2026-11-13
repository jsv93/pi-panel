#pragma once
#include "fleet_client.h"
#include <lwip/netdb.h>
#include <lwip/inet.h>
#include <esp_heap_caps.h>

namespace p4_runtime {
class AlbumClient {
 public:
  struct Frame {uint8_t *data=nullptr;size_t size=0;uint32_t version=0;};
  static constexpr size_t limit=384*1024;
  uint32_t generation()const{return generation_;}
  bool initialized()const{return jobs_ && result_;}
  void start(const char *origin,bool library_thumbnails=false){
    origin_=origin;
    thumbnails_=library_thumbnails;
    if(!*origin)return;
    jobs_=xQueueCreate(1,sizeof(Job));result_=xQueueCreate(1,sizeof(Frame));
  }
  void select(const char *entity,const std::string &value){
    if(!jobs_ || !result_ || (entity==last_entity_ && value==last_))return;
    last_entity_=entity;
    const uint32_t version=++generation_;
    Job job{};job.version=version;job.entity=entity;
    last_=value;
    if(value.size()<sizeof(job.url))memcpy(job.url,value.data(),value.size());
    xQueueOverwrite(jobs_,&job);
    if(!worker_)xTaskCreate([](void *p){static_cast<AlbumClient*>(p)->run();},"study_art",8192,this,1,&worker_);
  }
  bool take(Frame &f){return result_ && xQueueReceive(result_,&f,0)==pdTRUE;}
 private:
  struct Job {uint32_t version;const char *entity;char url[1536];};
  std::atomic<uint32_t> generation_{0};
  bool thumbnails_=false;
  const char *last_entity_="",*origin_="";
  std::string last_;
  QueueHandle_t jobs_{},result_{};
  TaskHandle_t worker_{};
  static std::string host(const std::string &url){
    const size_t offset=url.compare(0,8,"https://")==0?8:url.compare(0,7,"http://")==0?7:0;
    if(!offset)return {};
    const auto end=url.find_first_of("/?#",offset);
    const auto authority=url.substr(offset,end-offset);
    if(authority.empty() || authority.find('@')!=std::string::npos)return {};
    const auto port=authority.find(':');
    if(port!=std::string::npos && (port+1==authority.size() ||
       authority.find_first_not_of("0123456789",port+1)!=std::string::npos))return {};
    const auto name=authority.substr(0,port);
    return name.find_first_not_of("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-")==std::string::npos?name:"";
  }
  std::string local_picture(const std::string &url)const{
    const size_t scheme=url.find("://");
    const size_t path=scheme==std::string::npos?std::string::npos:url.find('/',scheme+3);
    if(path==std::string::npos || url.compare(path,12,"/imageproxy/")!=0)return url;
    // Music Assistant accepts a discrete set of sizes. Its inspected
    // image URLs contain only size and format options, including size=0
    // for an unbounded original. Leave signed and unknown queries intact.
    const size_t query=url.find('?',path);
    if(query==std::string::npos)return url;
    for(size_t start=query+1;start<=url.size();){
      const size_t end=url.find('&',start);
      const auto pair=url.substr(start,end-start);
      if(pair.compare(0,5,"size=")!=0 && pair.compare(0,4,"fmt=")!=0)return url;
      if(end==std::string::npos)break;
      start=end+1;
    }
    return url.substr(0,query)+(thumbnails_?"?size=160&fmt=jpg":"?size=512&fmt=jpg");
  }
  std::string trusted_url(std::string picture,const char *entity)const{
    if(picture.find_first_of("\r\n\\#")!=std::string::npos)return {};
    const std::string proxy="/api/media_player_proxy/"+std::string(entity)+"?";
    if(picture.compare(0,proxy.size(),proxy)==0)return std::string(origin_)+picture;
    const auto source=host(picture),ha=host(origin_);
    if(source.empty() || ha.empty())return {};
    // HA supplies absolute HTTPS media thumbnails. This client sends no
    // credentials, rejects redirects and verifies the server certificate.
    if(source==ha)return local_picture(picture);
    if(thumbnails_ && picture.rfind("https://",0)==0)return picture;
    // HA may advertise its numeric LAN address for the Music Assistant image
    // service while the panel uses its mDNS name. Never attach a fleet token.
    struct in_addr ip{};
    if(inet_pton(AF_INET,source.c_str(),&ip)!=1)return {};
    addrinfo hints{},*addresses=nullptr;hints.ai_family=AF_INET;
    if(getaddrinfo(ha.c_str(),nullptr,&hints,&addresses))return {};
    bool same=false;
    for(auto *a=addresses;a;a=a->ai_next)
      if(reinterpret_cast<sockaddr_in*>(a->ai_addr)->sin_addr.s_addr==ip.s_addr)same=true;
    freeaddrinfo(addresses);return same?local_picture(picture):std::string{};
  }
  Frame fetch(const Job &job){
    Frame f{};f.version=job.version;
    const auto url=trusted_url(job.url,job.entity);if(url.empty())return f;
    esp_http_client_config_t cfg{};cfg.url=url.c_str();cfg.timeout_ms=5000;
    cfg.disable_auto_redirect=true;cfg.crt_bundle_attach=esp_crt_bundle_attach;
    auto h=esp_http_client_init(&cfg);if(!h)return f;
    if(esp_http_client_open(h,0)==ESP_OK){
      const auto bytes=esp_http_client_fetch_headers(h);
      if(esp_http_client_get_status_code(h)==200 && bytes>=0 && size_t(bytes)<=limit){
        const size_t capacity=bytes?size_t(bytes):limit;
        f.data=static_cast<uint8_t*>(heap_caps_malloc(capacity,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
        while(f.data && f.size<capacity && generation_==job.version){
          int n=esp_http_client_read(h,reinterpret_cast<char*>(f.data)+f.size,std::min<size_t>(8192,capacity-f.size));
          if(n<=0)break;
          f.size+=n;
        }
        if(f.size<4 || (bytes && f.size!=capacity) || f.data[0]!=255 || f.data[1]!=216 ||
           f.data[f.size-2]!=255 || f.data[f.size-1]!=217){heap_caps_free(f.data);f.data=nullptr;f.size=0;}
      }
    }
    esp_http_client_cleanup(h);return f;
  }
  void run(){
    Job job{};
    for(;;){
      xQueueReceive(jobs_,&job,portMAX_DELAY);
      auto frame=fetch(job);
      if(frame.version!=generation_){heap_caps_free(frame.data);continue;}
      Frame old;
      if(xQueueReceive(result_,&old,0)==pdTRUE)heap_caps_free(old.data);
      xQueueSend(result_,&frame,0);
    }
  }
};
}
