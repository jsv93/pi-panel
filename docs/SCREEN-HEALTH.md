# Screen diagnostics, recovery and adaptive brightness

Panel Server 0.20.0 adds behaviour and administration controls. The panel's
markup, styles, page geometry, themes, palettes and navigation are unchanged.
The existing Pi Panel HA integration remains compatible; no HA restart or
integration upgrade is required for these features.

## Settings and operation

### Provisioning new panels (0.20.2)

Add a panel asks only for room, room label and template. After adding, open
**Display → Adaptive brightness**, select the room's illuminance/lux sensor
and enable adaptive brightness. Save before installing the panel or change it
later. New panels use fixed brightness until configured. Bindings are per
panel: templates never silently copy another room's brightness sensor. Version
0.20.2 removes the extra sensor picker introduced in the 0.20.1 Add panel form.

New records merge all screen defaults even when an older template lacks them.
Browser recovery and remote diagnostics are enabled by default; explicit
template opt-outs, limits and brightness tuning are retained. Every installer
path (command, SSH and SD-card first boot) uses this same saved configuration
and installs the current backlight helper. Existing panels retain their sensor
and settings when the software is updated.

Open a panel in Panel Server → Display. Adaptive brightness and Browser
recovery / remote diagnostics have a dedicated **Save screen behaviour**
button. This patches only those settings, preserving appearance, lighting,
media, sensor assignments and other unsaved form fields. The regular Save &
push, templates, export/import and config rollback also carry these settings.

### Adaptive brightness

- Disabled until an illuminance entity is selected and enabled. The dropdown
  offers HA sensors classified as illuminance or reporting lx/lux. A missing
  previously selected entity is retained so a disconnected device does not
  erase its assignment. Runtime readings must have lx/lux units.
- Minimum/maximum: 10/100% by default. Dark/bright room: 5/300 lux. Brightness
  interpolates against log(lux + 1), clamped at the endpoints.
- Transition: 5 seconds by default, reaching approximately 95% of a change in
  that time. Target requests are limited to once per second and unchanged
  levels are skipped. From 0.20.1 the local helper interpolates each target at
  50 Hz over one second, removing visible one-second jumps (physical settling
  trails the calculated curve by up to roughly a second). Only changed native
  hardware levels are written. Manual, wake and idle changes fade over 400 ms.
  A new request retargets from the current hardware level; screen-off cancels
  a pending fade and blanks immediately. Requests are serialized and the
  helper uses one locked worker, so old dimming cannot relight a blanked panel.
- Idle clock uses 25% of the adaptive level, with a 1% floor. Blanked stays
  blanked, even while readings change. Wake uses the current calculated level.
- The existing on-panel brightness slider gives a 10-minute manual override.
  It then resumes the sensor curve. No extra controls or labels are added to
  the panel itself. The readout follows the effective awake brightness.
- Invalid, unavailable, negative and non-lux readings are ignored. Hold the
  last valid lux reading through outages. Cache it locally per entity at most
  once a minute so reloads start from a useful value without excessive writes.
  Before any valid reading, use the existing default brightness.
- This release uses HA illuminance entities. Direct Pi light-sensor hardware
  is not required and is not provisioned by this release.

### Browser recovery

- Enabled by default, independently of the config server and HA connection.
- The fully initialized dashboard sends a JS heartbeat every 10 seconds,
  including when idle or blanked. Startup exceptions and the panel's fatal
  error overlay stop that heartbeat. A live WebSocket alone is insufficient.
- Allow 120 seconds after agent startup; stale threshold defaults to 90 seconds
  (configurable 60–600). HA disconnection alone never causes a restart.
- First try reloading the kiosk page. If it does not recover, restart only
  `cage-kiosk`, not the Pi, agent, Bluetooth scanner or lighting services.
- Wait at least 120 seconds between attempts. Default limit: 3 attempts per
  rolling hour (configurable 1–6). Attempt timestamps persist across agent
  restarts in `/opt/panel/browser-recovery.json`. Failed actions count too.
  Failure to persist the budget prevents the action from running.
- Once the limit is reached, monitor and report the fault without further
  actions until budget becomes available. Disabling recovery leaves monitoring
  active. Ordinary idle/blanking continues to send heartbeats.
- This detects a missing or unresponsive dashboard/main thread, not every
  possible GPU, cable or physical-display fault.

### Screen diagnostics

Panel → Diagnostics → **Capture screen** or **Refresh status and events**.

- Capture is a JPEG of the actual running Chromium viewport, not the server's
  configuration Preview. It does not wake the screen. Physical backlight state
  is reported separately: an image is not proof that the hardware is lit.
- Includes health, heartbeat age, current screen mode, adaptive state/lux,
  recoveries in the last hour and the latest 100 structured browser/recovery
  events. Events live in memory; they reset when the agent restarts.
- No raw journal dumps, console contents, URLs, tokens or configuration secrets
  are included. Browser failures report error types, not arbitrary messages.
- Capture and event requests require admin authentication, the panel's
  authenticated socket, and a signed server request. They are limited to one
  outstanding request per panel and at least 3 seconds between requests.
- Images are bounded (2 MB base64), on demand, never stored by Panel Server or
  sent in periodic heartbeats. Responses have `Cache-Control: no-store`.
- **Remote screen capture and event log** disables the feature at both ends.
  Basic health metrics remain available in normal panel heartbeats.
- Chromium's dedicated kiosk profile exposes DevTools only on 127.0.0.1:9222.
  The agent permits only screenshot/reload operations against its exact local
  panel URL. No debugging port is exposed through Panel Server or on the LAN.

## Deployment and rollback

The signed bundle includes the updated agent, panel HTML and kiosk launcher.
Changing the launcher causes one browser restart so its new localhost capture
endpoint becomes available. No additional apt packages are needed. The normal
config cache and signed-agent fallback remain in place.

Before deployment retain a Panel Server backup and the currently served bundle
(including launcher and panel HTML). Configuration history can undo settings;
restoring the preceding app/bundle undoes the software release. A full HA
restore is not needed for an ordinary settings reversal.

## Validation

`tests/test_backlight_ramp.py`: native hardware steps, retargeting, duplicate
requests, immediate blank, cancellation, externally blanked wake, hardware
range conversion and instant-transition compatibility against fake sysfs.

`tests/test_screen_health.py`: recovery decisions, durable limits, HA-outage
and blank-screen behaviour, request authentication/correlation, bounds,
disabled/offline cases and preserving existing config; provisioning from old
and new templates, per-room binding, opt-outs and validation before creation.

`tests/test_screen_ui.cjs`: real browser execution of the panel and ingress
admin, lux smoothing, invalid readings, idle/blank/wake, manual override,
heartbeat, missing sensor retention, save validation and unchanged assignments.

`tests/test_screen_cdp.cjs`: actual viewport capture and page reload against a
disposable local Chromium-family browser. Physical Pi acceptance still checks
capture, standby, health and brightness on the deployed device.
