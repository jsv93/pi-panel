# Changelog

## 0.27.1

- Show the latest build log inside P4 Diagnostics, restricted to authenticated administrators and the selected device's builds, with pairing credentials removed.

## 0.27.0

- Build and deploy private P4 firmware and artwork automatically after room changes, with progress and retry controls in Diagnostics.
- Preserve Home Assistant pairing, authenticate and encrypt per-device updates, resume interrupted transfers and roll back failed boots.
- Retain current and previous local artwork for offline use and recovery; bound storage used by completed server builds.
- Match Architectural popup entry motion, correct playback colour leakage and light-slider echoes, and remove transition colour banding.
- Bound framebuffer DMA allocations to keep Home's final frame consistent when internal memory is fragmented.
- Retry transient SD startup failures and keep encrypted management reachable while local artwork recovers.

## 0.26.3

- Supply Home Assistant library provider logos through the enrolled P4 connection, with bounded image conversion and transparency for local device caching.

## 0.26.2

- Show the native ESP32-P4 renderer, rendered frames per second and display refresh rate in device diagnostics.
- Display small-panel memory capacity in MiB and round processor temperatures for readability.

## 0.26.1

- Stream P4 doorbell video from Home Assistant Core using a ticket scoped to the configured camera when the add-on uses Supervisor authentication.

## 0.26.0

- Enrolled ESP32-P4 Study panels can cache their signed room configuration and synchronize display preferences.
- The doorbell test can ring a paired P4. The server sizes frames from the configured Home Assistant MJPEG camera for the panel.
- The CM5 kiosk also supports Home Assistant MJPEG camera playback.

## 0.25.0

- Add an optional Save power while asleep setting under Display. While fully blanked, limit CPU speed to its existing minimum and restore the original ceiling on wake or doorbell playback.
- Keep the normal governor, voltage, firmware, Bluetooth, Home Assistant connection and five-second performance sampling unchanged.
- Restore normal performance on missing/stale browser state, disable, shutdown and agent restart. Record power-saving status in display diagnostics.

## 0.24.0

- Add per-panel Doorbell settings with a Home Assistant camera selector, ring trigger, popup duration and Test doorbell button.
- Wake the panel for muted live WebRTC video, then release the stream on close, timeout, sleep, page hiding or connection failure. Repeated rings reuse one stream.
- Support Home Assistant ring sensors, event entities, input buttons and targeted automation events. Camera selection remains in the saved panel settings; no new listener or shell is exposed.
- Preserve normal dashboard controls and background optimizations. Cameras without live WebRTC support show a clear message instead of presenting a snapshot as live video.

## 0.23.3

- Stop unnecessary clock, uptime, media-progress and diagnostic frame updates while the panel is blanked or hidden; only animate playback progress where it is visible.
- Update displayed clocks on minute boundaries and defer asleep screen repaints until wake, using the latest state and elapsed playback time.
- Keep Home Assistant state, agent heartbeats, wake controls and adaptive backlight behavior active. CPU clock and power settings are unchanged.

## 0.23.2

- Keep historical readouts at their natural width near graph edges, while fitting narrow mobile screens.

## 0.23.1

- Hover over any performance graph to read its historical timestamp and value, with receive and send shown together for network traffic.
- Tooltips also support touch and keyboard navigation, preserve the selected sample during live refresh, label averaged readings, and leave missing-data gaps empty.

## 0.23.0

- Apply the new shared layout and left navigation across fleet, panel and server settings.
- Add real CPU, temperature, RAM, network, disk-write and load graphs. Live uses five-second samples over a rolling five-minute window, alongside 15-minute, 1-hour and 24-hour views. History is retained across server restarts and starts accumulating after upgrade.
- Move configuration history into a dropdown with restore confirmation. Preserve other device diagnostics as listed values.
- Add per-panel Access & SSH: read, add and remove computer public keys through the enrolled agent. Existing server keys are protected, changes are backed up and audited, and no interactive shell or extra listener is exposed.
- Keep configuration edits intact during diagnostics refresh and improve mobile navigation and keyboard access.

## 0.22.2

- Remove the separate secure diagnostics console, operator login, HTTPS
  listener and additional agent connection introduced in 0.21.0–0.22.1.
- Restore the original panel agent and dashboard behavior. Existing panel
  configuration, enrollment keys and provisioning SSH credentials are preserved.
- Remove the retired management policy, TLS files and audit database from the
  add-on data directory on startup. Normal SSH behavior is unchanged.
