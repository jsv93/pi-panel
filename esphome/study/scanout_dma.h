#pragma once
#include "esp_private/dw_gdma.h"
#include "esp_attr.h"
#include "esp_idf_version.h"

#if ESP_IDF_VERSION_MAJOR != 5 || ESP_IDF_VERSION_MINOR != 5
#error "Revalidate the DSI DMA retirement callback before changing ESP-IDF from 5.5"
#endif

namespace study {
inline volatile uint32_t scanout_dma_epoch=0;
inline bool scanout_dma_tracking=false;
}

extern "C" bool mipi_dsi_dma_trans_done_cb(dw_gdma_channel_handle_t,
    const dw_gdma_trans_done_event_data_t *,void *);
extern "C" esp_err_t __real_dw_gdma_channel_register_event_callbacks(
    dw_gdma_channel_handle_t,dw_gdma_event_callbacks_t *,void *);

static bool IRAM_ATTR study_scanout_dma_done(dw_gdma_channel_handle_t channel,
    const dw_gdma_trans_done_event_data_t *event,void *context){
  // IDF 5.5 restarts the next frame's DMA before this callback returns.
  // The completed buffer can now be reused without guessing from VSYNC.
  const bool yield=mipi_dsi_dma_trans_done_cb(channel,event,context);
  study::scanout_dma_epoch=study::scanout_dma_epoch+1;
  return yield;
}

extern "C" esp_err_t __wrap_dw_gdma_channel_register_event_callbacks(
    dw_gdma_channel_handle_t channel,dw_gdma_event_callbacks_t *callbacks,void *context){
  if(!callbacks || callbacks->on_full_trans_done!=mipi_dsi_dma_trans_done_cb)
    return __real_dw_gdma_channel_register_event_callbacks(channel,callbacks,context);
  auto tracked=*callbacks;
  tracked.on_full_trans_done=study_scanout_dma_done;
  const auto result=__real_dw_gdma_channel_register_event_callbacks(channel,&tracked,context);
  study::scanout_dma_tracking=result==ESP_OK;
  return result;
}
