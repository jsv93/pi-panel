# DALI integration: gateway API and degraded mode

The agent-side client is **built** (`agent/panel-agent.py`, `dali_*`) and tested
against a stub gateway; the per-light mapping and the panel UI switch are not.
Degraded mode is design only. Extends the topology already settled in
`ARCHITECTURE.md`: one application controller, panels as clients.

## What is wrong with the path today

    panel.html --(HA websocket, call_service)--> Home Assistant
      -> Lunatone gateway -> DALI bus -> control gear

Home Assistant is in the path of a light turning on. That contradicts the rule
this project is built around, and it is the least reliable link: HA restarts for
updates, HAOS falls over, the integration reloads. The gateway and the bus are
the reliable parts and they are downstream of the fragile one.

    panel.html -> agent --(HTTP/WS on the LAN)--> Lunatone gateway
      -> DALI bus -> control gear

Same number of hops, HA no longer among them. HA keeps working as a *client* of
the same gateway — automations, voice, schedules — it simply stops being load
bearing for the panel.

## The gateway API

Verified against Lunatone's DALI-2 IoT API documentation, M0023, rev 2022-04-06,
firmware v1.2. Confirm against your own unit's `/docs` — it serves a live
OpenAPI page and the firmware has moved since.

### Shape

Plain HTTP on port 80, JSON in and out. **No authentication in this firmware
version.** Anything that can reach the gateway can drive every light in the
building. Treat reachability as the access control: put it on the same isolated
VLAN as the panels and do not route it. Newer firmware appears to add an
optional bearer token (a third-party client exposes one); check yours and turn
it on if it is there.

### Control

One endpoint shape, four target scopes:

    POST /device/{id}/control
    POST /group/{id}/control
    POST /zone/{id}/control
    POST /broadcast/control

The body is a `ControlData` object — a map of feature name to value. Features are
optional and combinable, so one request can set level and colour together:

```json
{ "switchable": true }
{ "dimmable": 50 }            // 0-100 percent; 0 switches off
{ "gotoLastActive": true }
{ "scene": 15 }               // recall scene 0-15
{ "saveToScene": 15 }         // store current level as scene 0-15
{ "colorKelvin": 4000 }
{ "colorRGB": { "r": 0, "g": 0.5, "b": 1 } }     // 0-1 each
{ "colorXY":  { "x": 0.432, "y": 0.15 } }
```

`fadeTime` is absent from this revision but present in a third-party client for
newer firmware. Check `/docs` before relying on it.

Note `id` is the gateway's own registration number, **not** the DALI short
address. The two differ and only the gateway knows the mapping.

### State

    GET /devices

Returns every registered device with its features' current status:

```json
{ "devices": [ {
    "id": 1, "name": "DALI #0", "address": 0, "line": 0, "type": "default",
    "features": {
      "switchable":  { "status": false },
      "dimmable":    { "status": 0 },
      "colorKelvin": { "status": 2700 },
      "colorRGB":    { "status": { "r": 1, "g": 1, "b": 1 } },
      "scene": true, "saveToScene": true, "gotoLastActive": {}
    },
    "scenes": [], "groups": [], "daliTypes": [8]
} ] }
```

`daliTypes: [8]` is DT8 — the colour-capable device type. That is how the panel
should decide whether to draw a colour-temperature control, rather than by
configuration.

### Push

    ws://<gateway>/

Sends an `info` greeting on connect, then typed events, each with a `type`,
a `data`, and a `timeSignature` of `{timestamp, counter}`.

Useful here:

| Event | Carries |
|---|---|
| `devices` / `devicesDeleted` | device list with feature status, same shape as `GET /devices` |
| `daliStatus` | bus powered (2), unpowered (0), power low (5), interface failure (1) |
| `daliMonitor` | **every** frame on the bus, as raw integers |
| `scanProgress` | bus scan progress |
| `ping` | connection test, triggered by `POST /ping/echo` |

The client can suppress event types per connection:

```json
{ "type": "filtering", "data": { "daliMonitor": true } }
```

Filter `daliMonitor` out. It is one message per bus frame, it arrives as
undecoded address/opcode integers, and on a busy bus it will bury everything
else.

`daliStatus` is the valuable one and has no equivalent over HTTP: it is how the
panel learns the bus itself has lost power, which is a different failure from
the gateway being unreachable and should be shown differently.

### Discovery

The gateway answers UDP broadcasts on port 5555 containing the ASCII string
`discovery`:

```json
{ "type": "dali-2-iot", "name": "user defined name" }
```

Fallback static address with no DHCP is 169.254.0.1/16.

This is worth using: the config server can find gateways and offer them in a
dropdown, the way panels are provisioned now, rather than making someone type
an IP.

## The sketch

### Where it lives

In the **agent**, not in `panel.html`. The browser reloads; the agent does not.
The agent already holds a long-lived socket with reconnect (`ws_loop`), already
fans out to pages (`tell_pages`), and already survives the server being gone.
A gateway client is the same shape as what is there.

    panel.html --(localhost /agent ws)--> agent --(HTTP+WS)--> gateway

The panel keeps talking to one thing on localhost. Whether that resolves to HA,
the gateway, or a GPIO pin becomes the agent's problem, which is where the
fallback logic has to live anyway.

### Config

A `dali` block alongside `lights`, owned by the server like everything else:

```json
"dali": {
  "gateway": "http://dali-gw.local",
  "poll_s": 0
},
"lights": [
  { "name": "Downlights",
    "entity": "light.study_downlights",       // still HA, for state elsewhere
    "dali": { "type": "group", "id": 3 } }    // gateway target, optional
]
```

A light with no `dali` target keeps working exactly as it does now. That makes
this incremental — one room at a time, with the old path intact underneath.

### Flows

**Command.** Page sends `{type:"light", id, level}` to the agent. Agent maps the
light to its target and `POST`s the `ControlData`. Optimistically updates its
cache and echoes to pages so the slider does not wait on a round trip.

**State.** Agent holds the gateway websocket with `daliMonitor` filtered,
maintains a device cache from `devices` events, pushes deltas to pages. On
connect, one `GET /devices` to prime it.

**Failure.** Gateway unreachable, or `daliStatus` reports bus unpowered: agent
tells pages, UI changes mode (below).

### Open questions — settle these on the hardware, not here

1. **Does a level change from another controller push a `devices` event?** The
   manual's introduction says level changes are signalled over websocket, but
   §6.3.2 describes `devices` as firing when devices are *added*. If it does not
   push, the choices are polling `GET /devices` or decoding `daliMonitor`, and
   that decision changes the design. Sit on the socket, move a light from HA,
   and watch. **This is the first thing to test.**
2. Round-trip latency for a single `POST /device/{id}/control` on the LAN.
3. Whether `fadeTime` exists on your firmware.
4. Whether the API is authenticated on your firmware.

## Degraded mode

### The layers

| Layer | Path | Survives |
|---|---|---|
| 0 | panel → agent → gateway → bus | normal |
| 1 | panel → GPIO → opto → DALI input coupler → bus | LAN down, gateway down, HA down |
| 2 | wall switch → its own coupler → bus | panel down |
| 3 | gear's configured system failure level | bus down |

Layer 2 is the guarantee and already exists. Layer 1 is the addition, and it
only covers one case: **network or gateway dead, panel alive.** Be clear that
this is what is being bought, because it is narrower than it first sounds.

### Why an input coupler and not the panel on the bus

The panel cannot put frames on the bus itself. Two reasons, and the second is
the one that decides it:

- 16 V bus, 3.3 V GPIO. Needs a transceiver regardless.
- DALI is 1200 baud Manchester — 833 µs bits, 416 µs half-bits. A Pi running a
  Chromium kiosk cannot hold that timing. Linux scheduling jitter under load
  will exceed the tolerance and produce corrupt frames intermittently: fine on
  the bench, failing while the media browser scrolls. The timing must be owned
  by hardware.

So: dry contacts into a coupler that already does this properly.

### The coupler, and the thing to check

**Lunatone DALI-2 MC** — 4 potential-free inputs, bus-powered at 3.8 mA,
40 × 28 × 15 mm, so it fits in the panel's rear cavity. Each input is configured
with a **target address, button behaviour and DALI command**, via DALI Cockpit
or NFC.

**Verify before buying:** that it addresses control gear *directly* rather than
only emitting DALI-2 input-device events. This is the whole question. An input
device that emits events needs an application controller alive to interpret
them — which is precisely the thing that is dead in the scenario this exists
for, making the fallback useless. Lunatone describe the MC as multi-master and
its inputs are configured with target addresses, which is the right sign, but
confirm it: power the bus, unplug the gateway, press a button.

### What the panel gets

Four inputs, so four actions. The natural allocation maps onto what the panel
already has:

| Input | Action | Panel control |
|---|---|---|
| 1 | recall scene 0 | **Bright** preset tile |
| 2 | recall scene 1 | **Soft** preset tile |
| 3 | broadcast off | off |
| 4 | dim up/down on hold | the slider, coarsely |

Scenes are stored in the *gear*, not the gateway, so they survive the gateway
dying — that is what makes this work. Store them once with `saveToScene` while
everything is healthy: set the room how you want it, then
`POST /broadcast/control {"saveToScene": 0}`.

This is the elegant part: the degraded UI is the same UI. The two preset tiles
that already exist keep working, and they are the controls that actually get
used.

### What is lost

- **State feedback.** The panel cannot read the bus, so it does not know the
  level. The UI must stop showing one. A slider frozen at its last known
  position is worse than no slider — it is a lie about a room you are looking
  at. Show the presets, drop the level readout, say why.
- **Arbitrary levels.** Only what the four inputs are configured for.
- **Per-light control.** Targets are fixed at configuration time. A group or
  broadcast, not "just the lamp".
- **Colour temperature**, unless an input is spent on a macro.

### Detecting the switch

The agent already knows. Gateway websocket closed, or HTTP failing, or
`daliStatus` reporting unpowered — flip a flag, `tell_pages`, and the UI drops
to the reduced set. The plumbing is the same as the presence wake: a pin
configured per panel on the server, driven by the agent. Output rather than
input, but the same shape, and the config and diagnostics patterns are already
built.

Coming *back* should be automatic and quiet: gateway returns, `GET /devices`
re-primes the cache, the full UI returns.

### Wiring

Four GPIOs, each through an opto-isolator to a coupler input. Isolation is not
optional — the coupler's inputs are referenced to the bus side.

The panel's rear footprint is already spoken for by the PoE HAT. The MC is
small, but budget for it and the optos before committing to an enclosure.

## State of it

**Done.** The agent holds the gateway's websocket, primes its cache from
`GET /devices`, folds `devices` events into it, reports `daliStatus` separately
from an unreachable gateway, and exposes `POST /dali/control` and
`GET /dali/state` on localhost for the page. Configured per panel from the
server (`dali.gateway`, `dali.poll_s`); blank disables it and lights keep going
through Home Assistant. Status appears in Diagnostics as **DALI**.

Verified against a stub gateway built to the manual's shapes, 18 checks: config
parsing, cache priming, DT8 detection from `daliTypes`, dim, colour temperature,
scene recall to a group, bus power loss and recovery, bad targets, an
unreachable gateway, and reconfiguration while connected.

One thing that only showed up in testing: the loop originally read config once
per connection and iterated the socket. A healthy socket never drops, so a
gateway address pushed from the server would have taken effect only if the
connection happened to fail. It now receives with a timeout and re-reads on a
one-second tick.

**Not done.** Per-light DALI targets in the config, and the panel UI choosing
the gateway over Home Assistant for a light that has one. Both want the hardware
in front of them.

## Order of work

1. ~~Gateway API in the agent.~~ Done.
2. **Answer the push question** (§Open questions, item 1) the moment the gateway
   is on the bench. It decides whether the per-light work needs polling.
3. **Per-light targets and the UI switch.**
4. **Measure.** Find out how often layer 0 fails at all. The case for layer 1 is
   an assumption until there is a number against it.
5. **Degraded mode**, if the number justifies it.

Doing 5 before 4 would be building a fallback for a failure that has not been
observed, at the cost of board space that is already tight.
