# Architecture

Decisions and the reasoning behind them. Written so a future session (human or
Claude) doesn't re-litigate settled questions or repeat disproved theories.

## The independence requirement

Basic room function must not depend on Home Assistant, the network, or the
config server. This is the load-bearing constraint. It exists because a wall
switch that fails during an HA upgrade is unacceptable in a house someone lives
in — and because these are installed professionally, so "it works unless the
server is down" is not a defensible product.

Media control is explicitly exempt. Lighting is not.

## DALI topology

**Settled:** the guaranteed control path is bus-local hardware only —

    physical switch (DALI-2 control device)
      -> DALI bus
        -> application controller (DIN rail)
          -> control gear

No network, no HA, no panel in that path. Panels are a *convenience* layer on
top; losing one costs a touchscreen, not a light.

### Why not panel-as-DALI-master

The original design had each ESP32-P4 panel as a DALI application controller
with a Pico-DALI2 transceiver, alongside a Lunatone gateway. That is multiple
application controllers on one bus. DALI-2 permits it, but arbitration has to be
implemented correctly by every device, and a hobbyist ESPHome component almost
certainly does not. Two controllers also keep two state caches that can diverge.

Rejected in favour of: one application controller, panels as clients.

### Why not one bus segment per room

Considered as a way to dodge multi-master (each panel alone on its own bus).
Rejected: too much cable and too many PSUs for the benefit, and unnecessary once
panels stopped being masters.

### Optional: panel GPIO -> DALI input module

A panel can drive an opto-isolated dry contact into a DALI-2 input module,
giving it a network-independent control path. Worth having as a *degraded mode*
only: contacts can express toggle/dim/scene, not "set to 47%", and give no state
feedback. Primary control should go via the gateway's local API.

Both halves of that — the gateway's API and the degraded path — are sketched in
`DALI-INTEGRATION.md`, with the endpoint shapes, the coupler to use, and the one
property of it that has to be confirmed before buying.

## Platform

Two panel platforms, both viable:

- **ESP32-P4 + ESPHome** — cheap, boots in ~3s, tiny attack surface, LVGL 8.
  Motion is limited: no real blur, full-screen animation is not viable.
- **Raspberry Pi 5 / CM5 + Chromium kiosk** — GPU compositor, real glassmorphism,
  60fps. Costs more, boots in ~30s, has an OS to maintain.

The Pi is the chosen direction. The ESP remains supported in the config server
(`kind=esp`) in case it's wanted for secondary rooms.

**Compact CM5 build:** CM5 Lite + Waveshare CM5-NANO-B (same footprint as the
module, dual MIPI DSI, GbE) + a separate 802.3at PoE splitter. Plain 802.3af is
not enough headroom.

## Config server

Self-hosted FastAPI + SQLite, Docker on Unraid. Panels register themselves and
appear as unclaimed; you assign room and template through the GUI.

**Push and independence coexist:** panels hold a WebSocket for instant push and
fall back to polling. Config lives on the panel's disk. The server being down is
a non-event.

Deliberately *not* an HAOS add-on: it would couple panel management to HA
availability, which contradicts the whole point, and the OptiPlex running HAOS
is already memory-constrained. An add-on wrapper over the same image remains
possible later if Ingress/sidebar access is wanted.

## Open questions

- Does the chosen input module embed application-controller logic, so a button
  drives a group with nothing else running? Confirm with vendor.
- Multi-master behaviour if a panel is ever put back on the bus — needs bench
  testing with a gateway present before committing multiple rooms.
- Whether ESP panels are worth maintaining as a second platform long-term.
