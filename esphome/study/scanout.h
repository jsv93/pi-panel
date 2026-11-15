#pragma once
#include "esphome/components/mipi_dsi/mipi_dsi.h"
#include <esp_timer.h>
#include <esp_async_memcpy.h>
#include <esp_cache.h>
#include <freertos/semphr.h>
#include "framebuffer_copy.h"
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
    uint8_t *toast_background{};
    bool has_toast=false;
  };
  void (*restore_overlay)(Slot *)=nullptr;
  void (*draw_overlay)(Slot *,int &,int &)=nullptr;
  const uint8_t *visible_pixels()const{return submitted_?front_->pixels:nullptr;}
  void copy_visible_clean(Slot *slot){
    copy_pixels(slot->pixels,front_->pixels,720*1280*2);
    auto clean=*front_;clean.pixels=slot->pixels;
    if(restore_overlay)restore_overlay(&clean);
  }
  uint32_t presentation_count()const{return presented_count_;}
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
    if(copier_)xSemaphoreTake(copy_lock_,portMAX_DELAY);
    auto *out=static_cast<uint8_t*>(destination);
    auto *in=static_cast<const uint8_t*>(source);
    // IDF allocates internal DMA descriptors per transfer. A full frame needs
    // two long contiguous lists, competing with the SD and hosted-radio buffers.
    // Bound their size so an endpoint does not unexpectedly fall back to a
    // slow full-screen CPU copy when the small internal heap is fragmented.
    while(bytes){
      const size_t count=std::min(bytes,size_t(256*1024));
      if(copier_ && esp_async_memcpy(copier_,out,const_cast<uint8_t*>(in),count,copy_done,copied_)==ESP_OK)
        xSemaphoreTake(copied_,portMAX_DELAY);
      else{
        memcpy(out,in,count);
        esp_cache_msync(out,count,ESP_CACHE_MSYNC_FLAG_DIR_C2M|ESP_CACHE_MSYNC_FLAG_UNALIGNED);
      }
      bytes-=count;out+=count;in+=count;
    }
    if(copier_)xSemaphoreGive(copy_lock_);
  }
  // Main-renderer only: source is an already-flushed visible frame, destination
  // is a retired slot. Copying the viewport avoids moving stationary margins.
  bool copy_rect(uint8_t *destination,const uint8_t *source,int x,int to_y,int from_y,int w,int h){
    if(!rect_done_)rect_done_=xSemaphoreCreateBinary();
    if(!rect_copier_){esp_async_fbcpy_config_t config{};esp_async_fbcpy_install(&config,&rect_copier_);}
    if(!rect_done_ || !rect_copier_)return false;
    // Preserve dirty neighbouring pixels before invalidating complete cache
    // lines. The CPU does not touch this region again until DMA has finished.
    if(esp_cache_msync(destination+to_y*1440,h*1440,ESP_CACHE_MSYNC_FLAG_DIR_C2M|
        ESP_CACHE_MSYNC_FLAG_INVALIDATE|ESP_CACHE_MSYNC_FLAG_UNALIGNED)!=ESP_OK)return false;
    esp_async_fbcpy_trans_desc_t copy{};copy.src_buffer=source;copy.dst_buffer=destination;
    copy.src_buffer_size_x=copy.dst_buffer_size_x=720;
    copy.src_buffer_size_y=copy.dst_buffer_size_y=1280;
    copy.src_offset_x=copy.dst_offset_x=x;copy.src_offset_y=from_y;copy.dst_offset_y=to_y;
    copy.copy_size_x=w;copy.copy_size_y=h;
    copy.pixel_format_unique_id.color_type_id=COLOR_TYPE_ID(COLOR_SPACE_RGB,COLOR_PIXEL_RGB565);
    if(esp_async_fbcpy(rect_copier_,&copy,rect_done,rect_done_)!=ESP_OK)return false;
    xSemaphoreTake(rect_done_,portMAX_DELAY);return true;
  }
  Slot *acquire(bool wait,bool prepare_early=false) {
    const auto end=esp_timer_get_time()+80000;
    do {
      const uint32_t epoch=refresh_epoch();
      if(prepare_early || !submitted_ || epoch!=last_epoch_) {
        for(auto &s:slots_)
          if(&s!=front_ && int32_t(epoch-s.safe_after)>=0){
            if((s.has_overlay || s.has_toast) && restore_overlay)restore_overlay(&s);
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
  esp_async_fbcpy_handle_t rect_copier_{};
  SemaphoreHandle_t rect_done_{};
  static bool rect_done(esp_async_fbcpy_handle_t,esp_async_fbcpy_event_data_t*,void *context){
    BaseType_t woken=pdFALSE;xSemaphoreGiveFromISR(static_cast<SemaphoreHandle_t>(context),&woken);
    return woken==pdTRUE;
  }
  static bool copy_done(async_memcpy_handle_t,async_memcpy_event_t *,void *context){
    BaseType_t woken=pdFALSE;
    xSemaphoreGiveFromISR(static_cast<SemaphoreHandle_t>(context),&woken);
    return woken==pdTRUE;
  }
};
}
