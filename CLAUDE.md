# CLAUDE.md

Context for Claude Code working in this repo. Read `docs/ARCHITECTURE.md` for
the reasoning behind the constraints below — they were expensive to learn.

## What this is

A fleet of wall-mounted smart home control panels for a new-build house, plus
the server that configures them. Home Assistant provides automation and media;
it must **not** be required for basic room control.

## The one rule that shapes everything

**Nothing in the path of a light turning on may depend on the network, Home
Assistant, or the config server.** If a change makes a light dependent on
software that can be down, it is wrong — say so rather than implementing it.

Corollaries:
- The config server pushes config, never commands. Panels cache config on disk.
- The panel UI must boot and function with the config server unreachable.
- Media control may depend on HA. Lighting may not.

## Layout

    server/       FastAPI + SQLite config server (Docker, runs on Unraid)
    agent/        Panel-side sync agent; also serves the UI over localhost
    panel-ui/     panel.html — the Pi panel UI (single file, vanilla JS)
                  backlight.py — localhost sysfs brightness helper (systemd)
    esphome/      ESP32-P4 panel firmware (panel-poc.yaml)
    docs/         Architecture decisions and hardware findings

## Conventions

- Python: stdlib-first, no ORM, no framework beyond FastAPI. Type hints where
  they help; don't decorate everything.
- Panel UI: single self-contained HTML file, vanilla JS, no build step, no npm.
  This is deliberate — a panel must be debuggable over SSH at 2am.
- Comments explain *why*, especially where a non-obvious constraint forced the
  code's shape. Don't narrate what the code plainly does.
- Test what can be tested locally before claiming it works. `python -m py_compile`
  is not a test.

## Panel UI performance constraints (measured, not theoretical)

The Pi 5 renders 720x1280 with `backdrop-filter` glass. Frame budget is tight:

- **Never animate `filter`** — forces re-rasterisation every frame. Use
  `transform` and `opacity` only; both are compositor-only.
- **Never animate `width`/`height`** — layout properties. Slider fills use
  `transform: scaleX()` for this reason.
- Blur radius costs scale with radius. Lists of many `backdrop-filter` elements
  will tank frame rate; keep glass on hero elements only.
- The glass tier toggle in Settings exists to A/B this. Don't remove it.

## ESPHome panel constraints (ESP32-P4)

Every one of these cost hours to find:

- `psram: speed: 200MHz` is mandatory. The 20MHz default underruns the DPI
  scanout, wedges the DSI host, and trips the watchdog.
- The 5-DSI-TOUCH-A is **HX8394**, not the ILI9881C that the built-in 7" model
  uses. Wrong model = silent black screen. Init sequence came from Waveshare's
  `esp_lcd_hx8394` component.
- The panel needs an I2C wake (0x45: reg 0x95=0x11 then 0x17, reg 0x96 backlight)
  *before* display setup, or DSI writes block forever.
- `phy_addr: 1` for the IP101 Ethernet PHY on this board.
- `hardware_uart: UART0` — the board's USB-C is a CH343 on UART0; the P4 default
  (USB_SERIAL_JTAG) is unreachable there.
- Backlight needs `gamma_correct: 1.0`; the panel controller has its own curve.
- Board is engineering-sample silicon (rev v1.3). Set `engineering_sample: true`
  and `flash_size: 32MB`.
- `SPIRAM_XIP_FROM_PSRAM` took an LVGL benchmark from 7 to 63 fps by executing
  code from 200MHz PSRAM instead of 40MHz DIO flash.

## Things that look like bugs but aren't

- I2C "GPIO 7/8 not usable" warnings on the ESP panel: the HX8394 driver claims
  those pins on a legacy I2C port; touch works regardless.
- `lcd_panel: swap_xy/mirror not supported`: DPI panels can't rotate in hardware.

## Before proposing hardware changes

The measured position is that the ESP32-P4 panel is *usable* and the Pi 5 panel
is *better*. Neither is blocked on silicon. Check `docs/P4-FINDINGS.md` before
suggesting a board change — several plausible-sounding hardware theories were
tested and disproved.
