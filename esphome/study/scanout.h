#pragma once
#include "esphome/components/mipi_dsi/mipi_dsi.h"
#include <esp_timer.h>
#include <esp_async_memcpy.h>
#include <freertos/semphr.h>
#ifdef STUDY_DMA_RETIRE
#include "live_runtime/scanout_dma.h"
#endif

namespace study {
class Scanout {
 public:
  using Panel=esphome::mipi_dsi::MipiDsi;
  static uint32_t refresh_epoch(){
#ifdef STUDY_DMA_RETIRE
    if(scanout_dma_tracking)return scanout_dma_epoch;
#endif
    return Panel::refresh_epoch;
  }
  struct Slot {
    uint8_t *pixels{};
    uint32_t safe_after{}, page{},fixed_page{};
    bool lamp_background=false;
    uint8_t *overlay_background{};
    bool has_overlay=false;
  };
  void (*restore_overlay)(Slot *)=nullptr;
  void (*draw_overlay)(Slot *,int &,int &)=nullptr;
  const uint8_t *visible_pixels()const{return submitted_?front_->pixels:nullptr;}
  bool count_frame=true;
#ifdef STUDY_LIVE_CAPTURE
  const int64_t *frame_times()const{return presented_at_;}
#endif
  float rendered_fps()const{
    const auto now=esp_timer_get_time();
    unsigned count=0;
    for(const auto at:presented_at_)if(at && now-at<1000000)++count;
    return count;
  }
  bool begin(Panel *display) {
    if(!display)return false;
    void *a,*b,*c;
    panel_=display->native_panel();
    if(esp_lcd_dpi_panel_get_frame_buffer(panel_,3,&a,&b,&c)!=ESP_OK)return false;
    slots_[0].pixels=static_cast<uint8_t*>(a);
    slots_[1].pixels=static_cast<uint8_t*>(b);
    slots_[2].pixels=static_cast<uint8_t*>(c);
    async_memcpy_config_t copy_config=ASYNC_MEMCPY_DEFAULT_CONFIG();
    copy_config.backlog=1;copy_config.dma_burst_size=64;
    copied_=xSemaphoreCreateBinary();copy_lock_=xSemaphoreCreateMutex();
    if(copied_ && copy_lock_)esp_async_memcpy_install_gdma_axi(&copy_config,&copier_);
    active=true;
    return true;
  }
  void copy_pixels(void *destination,const void *source,size_t bytes){
    if(!copier_){memcpy(destination,source,bytes);return;}
    xSemaphoreTake(copy_lock_,portMAX_DELAY);
    if(esp_async_memcpy(copier_,destination,const_cast<void*>(source),bytes,copy_done,copied_)==ESP_OK)
      xSemaphoreTake(copied_,portMAX_DELAY);
    else memcpy(destination,source,bytes);
    xSemaphoreGive(copy_lock_);
  }
  Slot *acquire(bool wait,bool prepare_early=false) {
    const auto end=esp_timer_get_time()+80000;
    do {
      const uint32_t epoch=refresh_epoch();
      if(prepare_early || !submitted_ || epoch!=last_epoch_) {
        for(auto &s:slots_)
          if(&s!=front_ && int32_t(epoch-s.safe_after)>=0){
            if(s.has_overlay && restore_overlay)restore_overlay(&s);
            return &s;
          }
      }
      if(!wait)return nullptr;
      vTaskDelay(1);
    }while(esp_timer_get_time()<end);
    ESP_LOGW("study","Timed out waiting for display refresh");
    return nullptr;
  }
  bool present(Slot *slot,int first_y,int end_y) {
    const auto deadline=esp_timer_get_time()+80000;
    while(submitted_ && refresh_epoch()==last_epoch_){
      if(esp_timer_get_time()>=deadline)return false;
      vTaskDelay(1);
    }
    if(draw_overlay)draw_overlay(slot,first_y,end_y);
    if(esp_lcd_panel_draw_bitmap(panel_,0,first_y,720,end_y,slot->pixels)!=ESP_OK)return false;
    last_epoch_=refresh_epoch();
    // Allow two refresh boundaries for an already-started DMA scan to retire.
    front_->safe_after=last_epoch_+2;
#ifdef STUDY_DMA_RETIRE
    if(scanout_dma_tracking)front_->safe_after=last_epoch_+1;
#endif
    front_=slot;submitted_=true;
    if(count_frame)presented_at_[presented_count_++%128]=esp_timer_get_time();
    return true;
  }
  bool active=false;
  void invalidate_lamp(){for(auto &slot:slots_)slot.lamp_background=false;}
 private:
  esp_lcd_panel_handle_t panel_{};
  Slot slots_[3]{};
  Slot *front_=&slots_[0];
  uint32_t last_epoch_{};
  bool submitted_=false;
  uint32_t presented_count_=0;
  int64_t presented_at_[128]{};
  async_memcpy_handle_t copier_{};
  SemaphoreHandle_t copied_{},copy_lock_{};
  static bool copy_done(async_memcpy_handle_t,async_memcpy_event_t *,void *context){
    BaseType_t woken=pdFALSE;
    xSemaphoreGiveFromISR(static_cast<SemaphoreHandle_t>(context),&woken);
    return woken==pdTRUE;
  }
};
}
