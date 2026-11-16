# P4 live settings and artwork reuse

After installing this firmware once, Panel Server can update these settings through
the existing signed per-device configuration channel without rebuilding firmware:

- Idle/blank timers, default/minimum brightness, adaptive enable, sensor and curve.
- Temperature, humidity and thermostat entities.
- Doorbell enable, camera, trigger and duration.
- Speaker additions, removals, names, order and default (up to 16 including the default).
- P4 presence GPIO and retrigger interval.
- The existing gesture, scene, palette, diagnostics, mini-art and browse-view settings.

Changes apply between interactions/animations, normally on the next five-second
sync. Entity reassignment clears old values and reconnects the encrypted HA API
once to replace its subscriptions. Subscription storage is bounded. Other setting
changes do not reconnect HA. The signed configuration is cached atomically and
used after a restart without Panel Server; direct HA controls and compatible
camera streaming still require Home Assistant and the network.

All existing on-panel controls remain. Pi browser/power/GPIO settings retain their
values and behaviour. P4 settings show its own presence input instead: off by
default, GPIO 2 or 3, active-high 3.3 V input with a pulldown, and a 500–60000 ms
retrigger interval. These pins are exposed and unused by this display/Wi-Fi/SD/
Ethernet configuration in the [Waveshare board schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf).
A wired sensor is needed to complete a physical presence-wake test.

New light controls, light labels, backgrounds and display hardware remain structural
changes. DSI settings do not become live hardware changes.

The selected speaker follows its entity ID across list reorderings. Removing it
clears its controls and selects the configured default; a pending transfer is
never retargeted. Empty lists show “No speakers configured”. Speaker subscriptions
are registered once per slot and rebound on changes. The first firmware upgrade
adds this capability; subsequent list edits use no compiler or artwork build.
Speaker rows are cached only while the picker is open; drag/coast rendering does
not read artwork from the SD card or decompress full screens.

The build worker keeps a private per-device visual cache keyed by layout, control
capabilities, renderer sources, panel HTML and fonts. It verifies the complete
file list, sizes and SHA-256 hashes before reuse. Missing/corrupt entries render
again. Firmware sources, credentials and signed enrollment/configuration are
never cached as artwork; firmware inputs are always regenerated. A compiler-only
iteration can reuse all visual products, including transitions and Identify art.
`build.py JOB --prepare-only` exercises preparation without invoking the compiler.

The local trial uses the same authenticated server application. Its device
enrollment, database and artwork cache are separate from the HA add-on. No cloud
build or GitHub publication is required for a local iteration.
