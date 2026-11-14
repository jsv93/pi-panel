#pragma once
#include "config_store.h"
#include <driver/temperature_sensor.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>

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
};
}
