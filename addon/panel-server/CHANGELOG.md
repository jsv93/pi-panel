# Changelog

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
