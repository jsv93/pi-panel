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
  **One exception, deliberately narrow:** the server may run the bootstrap over
  SSH on a panel it is *currently provisioning*. It is gated on an unused
  provisioning token, so it cannot reach hardware already in service — those
  take config through their agent and never commands. Key-based only; the key
  goes on at flash time via Raspberry Pi Imager.
- The panel UI must boot and function with the config server unreachable.
- Media control may depend on HA. Lighting may not.

## Layout

    server/       FastAPI + SQLite config server (Docker, runs on Unraid)
    agent/        Panel-side sync agent; also serves the UI over localhost
    panel-ui/     panel.html — the Pi panel UI (single file, vanilla JS)
                  backlight.py — localhost sysfs brightness helper (systemd)
    pi-os/        Pi OS Lite kiosk boot: cage + systemd, no desktop session
    esphome/      ESP32-P4 panel firmware (panel-poc.yaml) — retired, see below
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

## What a panel may change about itself

Three things, and the list is closed:

- its own screen — backlight, glass tier, diagnostics, wifi (local, not config)
- the Soft and Bright **levels**, captured from whatever is on the sliders
- whether one light **takes part** in Soft and Bright

Everything else — which lights the panel has, which speaker it drives, its
room, its screen type — is configured on the server. The two writes above exist
because setting a room's levels from a computer while standing in the room is
absurd, and because choosing the levels is no use without choosing which lights
they apply to. That is the whole justification, and it does not extend.

Both go through the agent to narrow server endpoints that touch one field
each, never through a general config write. A panel cannot author its own
configuration and should not be given a way to.

## Panel UI performance constraints (measured, not theoretical)

The Pi 5 renders 720x1280 with `backdrop-filter` glass. Frame budget is tight:

- **Never animate `filter`** — forces re-rasterisation every frame. Use
  `transform` and `opacity` only; both are compositor-only.
- **Never animate `width`/`height`** — layout properties. Slider fills use
  `transform: scaleX()` for this reason.
- Blur radius costs scale with radius. Lists of many `backdrop-filter` elements
  will tank frame rate; keep glass on hero elements only.
- The glass tier toggle in Settings exists to A/B this. Don't remove it. It now
  ships at "Off": measured, the three glass surfaces (.tile, .nav, .sheet) cost
  24 composited blur passes a frame and produce nothing visible, because every
  one of them sits at 74-98% opacity over a near-black page whose only detail is
  two very soft radial gradients. A blur needs high-frequency content behind it
  and this UI has none. Ambient never had glass at all, which is the whole of
  why it measured faster.
- Theme and palette are separate. A theme is structure -- geometry, type,
  whether a surface has an edge. A palette is colour. Anything colour-shaped in
  a theme block is a bug; put it in the palette tokens so it works under both.
- **Every scrolling container needs `will-change: transform`.** The whole stage
  sits under a `transform: scale()`, and a scroller inside a transformed
  ancestor is not given its own compositing layer — so each frame of a flick
  repaints the list instead of moving a layer already drawn. Measured on the
  panel: 14fps without it, 64 with. Applies to any new scroller, not just the
  media browser.
- Diagnostics → **Scroll test** A/Bs six suspects over a synthetic 200-row list
  and prints the frame rates. Reach for it before optimising anything about
  scrolling. Three releases of plausible page-level work — lazy thumbnails,
  content-visibility, chunked rendering, dropping a sheet's `backdrop-filter` —
  were each worth one or two frames, against 4.5x for one line of CSS about
  compositing. Don't remove it either.
- Once a list is promoted the panel tops out around 65fps, and removals of
  unrelated things (text, thumbnails, borders, content-visibility) all land
  within ~10% of each other. That flatness means the ceiling, not four
  findings; don't chase it.

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
- Presence wake reporting `FAILED: ModuleNotFoundError` in diagnostics: the panel
  predates `python3-gpiozero` being in the bootstrap. The agent reaches panels by
  bundle update; apt packages do not. Install it on the panel once.

## Before proposing hardware changes

The measured position is that the ESP32-P4 panel is *usable* and the Pi 5 panel
is *better*. Neither is blocked on silicon. Check `docs/P4-FINDINGS.md` before
suggesting a board change — several plausible-sounding hardware theories were
tested and disproved.

## ESP32-P4: retired

The fleet is Pi-only. `esphome/` is kept for reference and is not maintained.

The reason was a **feature ceiling in LVGL versus a browser**, not silicon: no
backdrop blur, no widgets built at runtime from pushed config (so applying a
config change means a recompile), and no way to parse `browse_media` responses
into a UI. The panels could not be made to match, and the gap was permanent.
Do not read this as the P4 being incapable — `docs/P4-FINDINGS.md` says the
opposite and stands.
