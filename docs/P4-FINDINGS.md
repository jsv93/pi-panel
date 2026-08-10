# ESP32-P4 panel: findings

Bring-up notes for the Waveshare ESP32-P4-WIFI6-POE-ETH + 5-DSI-TOUCH-A.
Recorded because several of these present as "the screen is black" with no
diagnostic, and because a few plausible theories were tested and disproved.

## Working config (see esphome/panel-poc.yaml)

| Setting | Why |
|---|---|
| `psram: speed: 200MHz` | 20MHz default underruns DPI scanout → DSI wedges → WDT reset loop |
| `model: CUSTOM` + HX8394 init | The 5" panel is HX8394; the built-in 7" model is ILI9881C. Wrong model = silent black screen |
| I2C wake before display setup | 0x45: reg 0x95=0x11, then 0x17; reg 0x96 backlight. Without it DSI writes block forever |
| `phy_addr: 1` | IP101 straps to SMI address 1; default 0 gives "power up timeout" |
| `hardware_uart: UART0` | Board USB-C is a CH343 on UART0. P4 default USB_SERIAL_JTAG is unreachable |
| `gamma_correct: 1.0` on backlight | Panel controller has its own curve; ESPHome's 2.8 crushed low levels to black |
| `flash_size: 32MB` | Board has 32MB NOR but was running as 4MB |
| `engineering_sample: true` | Silicon is rev v1.3 (< v3.0) |
| `SPIRAM_XIP_FROM_PSRAM` | Executes code from 200MHz PSRAM instead of 40MHz DIO flash |

## Performance: measured

LVGL 9.5 `lv_demo_benchmark`, 720x1280:

| Config | Avg FPS |
|---|---|
| Baseline (defaults) | 7 |
| + PPA draw unit | 7 (no measurable gain) |
| + XIP from PSRAM, dual draw units, 256KB L2 | 63 peak, 14 avg |

The average is dragged down by software image transforms (rotating album art).
Simple UI content — fills, borders, text, sliders — sits near the ceiling.

## Theories tested and disproved

- **"Engineering-sample silicon is the bottleneck"** — the v1.3 chip is locked to
  40MHz DIO flash, which looked like the cause. It isn't: XIP-from-PSRAM
  bypasses flash entirely and recovers the performance. Do not buy new boards on
  this basis.
- **"PPA hardware acceleration will help"** — enabling it changed nothing on this
  workload. PPA accelerates fills and image blending; the bottleneck was
  elsewhere.
- **"A lighter OS/compositor will help the Pi"** — `cage` tested no better than
  the desktop session. (Caveat: the test ran nested over a live desktop, so it
  wasn't clean. Redo properly before relying on the result.)

## Gotchas that waste time

- LVGL 9.5's software image transform hangs under multi-threaded draw units.
  Pin LVGL to 9.2 and `esp_lvgl_port` < 2.8.0 (2.8.0 needs LVGL 9.3+).
- `LV_DRAW_SW_DRAW_UNIT_CNT > 1` requires `CONFIG_LV_OS_FREERTOS=y`.
- `LV_ATTRIBUTE_FAST_MEM_USE_IRAM` overflows IRAM with LVGL 9.5 + dual draw units.
- ESP-IDF < 5.4 has no ESP32-P4 target at all.
- `sdkconfig.defaults` cannot override a symbol already present in `sdkconfig`.
  Delete `sdkconfig` to apply changed defaults — but that also discards anything
  set via menuconfig.
