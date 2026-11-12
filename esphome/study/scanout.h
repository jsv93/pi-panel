#pragma once
#include "esphome/components/mipi_dsi/mipi_dsi.h"
#include <esp_timer.h>

namespace study {
class Scanout {
 public:
  using Panel=esphome::mipi_dsi::MipiDsi;
  struct Slot {
    uint8_t *pixels{};
    uint32_t safe_after{}, page{};
    bool lamp_background=false;
  };
  bool begin(Panel *display) {
    if(!display)return false;
    void *a,*b,*c;
    panel_=display->native_panel();
    if(esp_lcd_dpi_panel_get_frame_buffer(panel_,3,&a,&b,&c)!=ESP_OK)return false;
    slots_[0].pixels=static_cast<uint8_t*>(a);
    slots_[1].pixels=static_cast<uint8_t*>(b);
    slots_[2].pixels=static_cast<uint8_t*>(c);
    active=true;
    return true;
  }
  Slot *acquire(bool wait) {
    const auto end=esp_timer_get_time()+80000;
    do {
      const uint32_t epoch=Panel::refresh_epoch;
      if(!submitted_ || epoch!=last_epoch_) {
        for(auto &s:slots_)
          if(&s!=front_ && int32_t(epoch-s.safe_after)>=0)return &s;
      }
      if(!wait)return nullptr;
      vTaskDelay(1);
    }while(esp_timer_get_time()<end);
    ESP_LOGW("study","Timed out waiting for display refresh");
    return nullptr;
  }
  bool present(Slot *slot,int first_y,int end_y) {
    if(esp_lcd_panel_draw_bitmap(panel_,0,first_y,720,end_y,slot->pixels)!=ESP_OK)return false;
    last_epoch_=Panel::refresh_epoch;
    // Allow two refresh boundaries for an already-started DMA scan to retire.
    front_->safe_after=last_epoch_+2;
    front_=slot;submitted_=true;
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
};
}
