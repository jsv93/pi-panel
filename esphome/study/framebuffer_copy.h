// ESP-IDF 5.5 framebuffer-copy ABI, from esp_lcd/priv_include/esp_async_fbcpy.h.
// SPDX-FileCopyrightText: 2023-2024 Espressif Systems (Shanghai) CO LTD
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <esp_idf_version.h>
#include <esp_err.h>
#include <hal/color_types.h>
#if ESP_IDF_VERSION_MAJOR != 5 || ESP_IDF_VERSION_MINOR != 5
#error "Revalidate the framebuffer-copy ABI before changing ESP-IDF from 5.5"
#endif
// The driver is linked by esp_lcd, but its declarations are private to that
// component. Keep its ABI here rather than modifying the installed framework.
extern "C" {
typedef struct esp_async_fbcpy_context_t *esp_async_fbcpy_handle_t;
typedef struct {} esp_async_fbcpy_config_t;
typedef struct {
  const void *src_buffer;
  void *dst_buffer;
  size_t src_buffer_size_x,src_buffer_size_y;
  size_t dst_buffer_size_x,dst_buffer_size_y;
  size_t src_offset_x,src_offset_y,dst_offset_x,dst_offset_y;
  size_t copy_size_x,copy_size_y;
  color_space_pixel_format_t pixel_format_unique_id;
} esp_async_fbcpy_trans_desc_t;
typedef struct {} esp_async_fbcpy_event_data_t;
typedef bool (*esp_async_fbcpy_event_callback_t)(esp_async_fbcpy_handle_t,esp_async_fbcpy_event_data_t*,void*);
esp_err_t esp_async_fbcpy_install(const esp_async_fbcpy_config_t*,esp_async_fbcpy_handle_t*);
esp_err_t esp_async_fbcpy(esp_async_fbcpy_handle_t,esp_async_fbcpy_trans_desc_t*,esp_async_fbcpy_event_callback_t,void*);
}
