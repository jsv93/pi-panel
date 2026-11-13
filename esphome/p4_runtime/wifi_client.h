#pragma once
#ifdef USE_ESP32_HOSTED
#include <esp_wifi.h>
#include <esp_netif.h>
#include <esp_timer.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <vector>

namespace p4_runtime {
class WifiClient {
 public:
  struct Network {char ssid[33]{}; uint8_t signal=0; bool secure=false;};
  enum class State {idle,scanning,ready,joining,connected,failed};
  struct Result {State state=State::idle; std::vector<Network> networks; char ssid[33]{};int signal=0;};
  WifiClient(){
    queue_=xQueueCreate(1,sizeof(Job));
    guard_=xSemaphoreCreateMutex();
  }
  bool restore(){Job job{};job.restore=true;return request(job);}
  bool scan(){return request(Job{});}
  bool join(const char *ssid,const char *password){
    Job job{};job.connect=true;
    if(!ssid || !password || !*ssid || strlen(ssid)>32 || strlen(password)>63)return false;
    memcpy(job.ssid,ssid,strlen(ssid));
    memcpy(job.password,password,strlen(password));
    const bool accepted=request(job);
    explicit_bzero(job.password,sizeof(job.password));
    return accepted;
  }
  Result snapshot(){
    if(!guard_)return {};
    xSemaphoreTake(guard_,portMAX_DELAY);auto result=result_;xSemaphoreGive(guard_);
    return result;
  }
 private:
  struct Job {bool connect=false,restore=false;char ssid[33]{},password[64]{};};
  QueueHandle_t queue_{};SemaphoreHandle_t guard_{};TaskHandle_t worker_{};
  esp_netif_t *station_{};bool ready_=false;
  Result result_;
  bool request(const Job &job){
    if(!guard_ || !queue_)return false;
    if(!worker_ && xTaskCreate([](void *v){static_cast<WifiClient*>(v)->run();},"study_wifi",8192,this,2,&worker_)!=pdPASS)return false;
    xSemaphoreTake(guard_,portMAX_DELAY);
    const bool busy=result_.state==State::scanning || result_.state==State::joining;
    const bool accepted=!busy && xQueueSend(queue_,&job,0)==pdTRUE;
    if(accepted)result_.state=job.connect || job.restore?State::joining:State::scanning;
    xSemaphoreGive(guard_);return accepted;
  }
  bool start(){
    if(ready_)return true;
    if(!station_)station_=esp_netif_create_default_wifi_sta();
    if(!station_)return false;
    wifi_init_config_t cfg=WIFI_INIT_CONFIG_DEFAULT();
    if(esp_wifi_init(&cfg)!=ESP_OK)return false;
    if(esp_wifi_set_mode(WIFI_MODE_STA)==ESP_OK && esp_wifi_start()==ESP_OK){ready_=true;return true;}
    esp_wifi_deinit();return false;
  }
  bool scan_networks(Result &result){
    wifi_scan_config_t config{};
    if(esp_wifi_scan_start(&config,true)!=ESP_OK)return false;
    uint16_t count=0;
    if(esp_wifi_scan_get_ap_num(&count)!=ESP_OK){esp_wifi_clear_ap_list();return false;}
    count=std::min<uint16_t>(count,32);
    std::vector<wifi_ap_record_t> records(count);
    if(count && esp_wifi_scan_get_ap_records(&count,records.data())!=ESP_OK){esp_wifi_clear_ap_list();return false;}
    esp_wifi_clear_ap_list();
    for(const auto &ap:records){
      if(!ap.ssid[0])continue;
      Network net{};
      memcpy(net.ssid,ap.ssid,32);
      net.signal=std::clamp(2*(int(ap.rssi)+100),0,100);
      net.secure=ap.authmode!=WIFI_AUTH_OPEN;
      if(std::none_of(result.networks.begin(),result.networks.end(),[&](const Network &n){return strcmp(n.ssid,net.ssid)==0;}))
        result.networks.push_back(net);
    }
    result.state=State::ready;return true;
  }
  bool has_lease(const char *ssid){
    const auto end=esp_timer_get_time()+20000000;
    while(esp_timer_get_time()<end){
      wifi_ap_record_t ap{};esp_netif_ip_info_t info{};
      if(esp_wifi_sta_get_ap_info(&ap)==ESP_OK && strcmp(reinterpret_cast<const char*>(ap.ssid),ssid)==0 &&
         esp_netif_get_ip_info(station_,&info)==ESP_OK && info.ip.addr)return true;
      vTaskDelay(pdMS_TO_TICKS(250));
    }
    return false;
  }
  bool connect(const Job &job){
    wifi_config_t old{},next{};
    if(esp_wifi_get_config(WIFI_IF_STA,&old)!=ESP_OK)return false;
    memcpy(next.sta.ssid,job.ssid,strlen(job.ssid));
    memcpy(next.sta.password,job.password,strlen(job.password));
    next.sta.threshold.authmode=job.password[0]?WIFI_AUTH_WPA2_PSK:WIFI_AUTH_OPEN;
    // Test in RAM. Commit to the IDF station profile only after DHCP.
    bool linked=false;
    if(esp_wifi_set_storage(WIFI_STORAGE_RAM)==ESP_OK){
      esp_wifi_disconnect();
      linked=esp_wifi_set_config(WIFI_IF_STA,&next)==ESP_OK && esp_wifi_connect()==ESP_OK && has_lease(job.ssid);
      linked=linked && esp_wifi_set_storage(WIFI_STORAGE_FLASH)==ESP_OK && esp_wifi_set_config(WIFI_IF_STA,&next)==ESP_OK;
      if(!linked){
        esp_wifi_disconnect();
        esp_wifi_set_storage(WIFI_STORAGE_RAM);
        if(esp_wifi_set_config(WIFI_IF_STA,&old)==ESP_OK && old.sta.ssid[0])esp_wifi_connect();
        esp_wifi_set_storage(WIFI_STORAGE_FLASH);
      }
    }
    explicit_bzero(&old,sizeof(old));explicit_bzero(&next,sizeof(next));
    return linked;
  }
  void run(){
    for(;;){
      Job job{};xQueueReceive(queue_,&job,portMAX_DELAY);
      Result next;
      bool ok=start();
      if(ok && job.restore){
        wifi_config_t saved{};
        if(esp_wifi_get_config(WIFI_IF_STA,&saved)==ESP_OK && saved.sta.ssid[0]){
          char name[33]{};memcpy(name,saved.sta.ssid,32);
          ok=esp_wifi_connect()==ESP_OK && has_lease(name);if(ok)next.state=State::connected;
        }
        explicit_bzero(&saved,sizeof(saved));
      }else if(ok && job.connect){
        next=snapshot();ok=connect(job);if(ok)next.state=State::connected;
      }else if(ok)ok=scan_networks(next);
      if(!ok)next.state=State::failed;
      wifi_ap_record_t ap{};
      memset(next.ssid,0,sizeof(next.ssid));
      if(ready_ && esp_wifi_sta_get_ap_info(&ap)==ESP_OK){
        memcpy(next.ssid,ap.ssid,32);next.signal=std::clamp(2*(int(ap.rssi)+100),0,100);
      }
      explicit_bzero(&job,sizeof(job));
      xSemaphoreTake(guard_,portMAX_DELAY);result_=std::move(next);xSemaphoreGive(guard_);
    }
  }
};
}
#endif
