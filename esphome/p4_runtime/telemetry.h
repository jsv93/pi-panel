#pragma once
#include "config_store.h"
#include <driver/temperature_sensor.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>
#include <esp_system.h>
#include <esp_ota_ops.h>
#ifdef USE_ESP32_HOSTED
#include <esp_wifi.h>
#endif
#ifdef STUDY_SD_ONLY
#include "deployment_build.h"
#include "card_art.h"
#endif

namespace p4_runtime {
class Telemetry {
 public:
  void begin(){
    temperature_sensor_config_t config=TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10,80);
    if(temperature_sensor_install(&config,&temperature_)==ESP_OK)
      temperature_sensor_enable(temperature_);
  }
  void sample(cJSON *metrics){
    auto number=[metrics](const char *key,double value){cJSON_AddNumberToObject(metrics,key,value);};
    const int64_t now=esp_timer_get_time();
    number("uptime_s",now/1000000);
    number("cpu_cores",portNUM_PROCESSORS);
    float temperature;
    if(temperature_ && temperature_sensor_get_celsius(temperature_,&temperature)==ESP_OK)
      number("cpu_temp",temperature);
    const auto total=heap_caps_get_total_size(MALLOC_CAP_8BIT);
    const auto available=heap_caps_get_free_size(MALLOC_CAP_8BIT);
    number("ram_total_mb",total/1048576.);
    number("ram_used_mb",(total-available)/1048576.);
    if(total)number("ram_used_pct",100.*(total-available)/total);
    number("internal_free_kb",heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)/1024.);
    number("internal_min_free_kb",heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)/1024.);
    number("psram_free_mb",heap_caps_get_free_size(MALLOC_CAP_SPIRAM)/1048576.);
    number("psram_min_free_mb",heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM)/1048576.);
    number("reset_reason",esp_reset_reason());
    const auto *partition=esp_ota_get_running_partition();
    if(partition){
      cJSON_AddStringToObject(metrics,"firmware_slot",partition->label);
      esp_ota_img_states_t state{};
      if(esp_ota_get_state_partition(partition,&state)==ESP_OK)number("firmware_state",state);
    }
#ifdef USE_ESP32_HOSTED
    wifi_ap_record_t ap{};
    if(esp_wifi_sta_get_ap_info(&ap)==ESP_OK)number("wifi_rssi_dbm",ap.rssi);
#endif
#ifdef STUDY_SD_ONLY
    number("firmware_generation",STUDY_BUILD_GENERATION);
    // Storage work stays on the fleet worker and is bounded to once a minute.
    if(!storage_at_ || now-storage_at_>=60000000){
      study::CardArt card;storage_ok_=card.space(storage_total_,storage_free_);storage_at_=now;
    }
    cJSON_AddBoolToObject(metrics,"sd_ready",storage_ok_);
    if(storage_ok_){number("sd_total_mb",storage_total_/1048576.);number("sd_free_mb",storage_free_/1048576.);}
#endif
#if configGENERATE_RUN_TIME_STATS && configUSE_TRACE_FACILITY
    uint64_t idle_delta=0;
    for(int core=0;core<portNUM_PROCESSORS;++core){
      TaskStatus_t status{};
      vTaskGetInfo(xTaskGetIdleTaskHandleForCore(core),&status,pdFALSE,eInvalid);
      const uint32_t idle=status.ulRunTimeCounter;
      idle_delta+=uint32_t(idle-idle_[core]);idle_[core]=idle;
    }
    // ESP-IDF's ESP timer runtime source is in microseconds. Sample differences
    // across both idle tasks, including unsigned counter rollover.
    if(previous_ && now>previous_)
      number("cpu_usage_pct",std::clamp(100.*(1.-double(idle_delta)/((now-previous_)*portNUM_PROCESSORS)),0.,100.));
    previous_=now;
#endif
  }
 private:
  temperature_sensor_handle_t temperature_{};
  int64_t previous_=0;
  uint32_t idle_[portNUM_PROCESSORS]{};
#ifdef STUDY_SD_ONLY
  int64_t storage_at_=0;
  uint64_t storage_total_=0,storage_free_=0;
  bool storage_ok_=false;
#endif
};
}
