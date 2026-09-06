# pi-panel

Wall-mounted touch panels for a house, plus the server that configures them.
Raspberry Pi 5 and 3B+ behind Waveshare DSI screens, running Chromium in a kiosk
on Pi OS Lite. Home Assistant provides automation and media.

**Home Assistant is not required for a light to turn on.** That rule shapes
everything here: panels cache their configuration on disk and run from it when
the server is unreachable, the config server pushes configuration and never
commands, and where a DALI gateway is configured the panel talks to it directly
on the LAN rather than through HA. Losing Home Assistant, the network, or the
config server costs convenience and visibility — never a room's lights.

## Parts

| | |
|---|---|
| `panel-ui/` | `panel.html` — the panel interface. One file, vanilla JS, no build step |
| `agent/` | panel-side sync agent; also serves the UI over localhost |
| `server/` | FastAPI + SQLite config server, packaged as a Home Assistant add-on |
| `custom_components/pi_panel/` | the Home Assistant integration (this repo is HACS-installable) |
| `addon/` | add-on packaging, synced to its own repository by `addon/sync.sh` |
| `pi-os/` | Pi OS Lite kiosk boot — cage + systemd, no desktop session |
| `docs/` | architecture decisions and hardware findings |
| `tests/` | a stub DALI gateway and the harnesses that drive it |

## The Home Assistant integration

One device per panel, with its state, whether its configuration is current, and
buttons to identify, wake, sleep, reload, sync and restart it. Sensors cover
CPU temperature, disk headroom, card writes, backlight, presence and the DALI
gateway.

**It is not required for a panel to work.** Panels pull configuration from the
config server directly, so this integration being broken — or Home Assistant
being down — costs visibility and nothing else. That is the point of the split.

Install it through HACS as a custom repository, or copy
`custom_components/pi_panel` into your Home Assistant `config/custom_components/`.
Then **Settings → Devices & Services → Add Integration → Pi Panel**.

Full notes, including what it asks for and why: [docs/INTEGRATION.md](docs/INTEGRATION.md).

## The config server

Runs as a Home Assistant add-on, behind ingress. It provisions panels over SSH
while they are being installed, then only ever pushes configuration to them.

Set a real `admin_password` before putting it on a network — `host_network` means
it answers on port 8099 directly, bypassing Home Assistant's own authentication.
The GUI warns while the shipped default is still in place.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the decisions, and what was rejected
- [docs/DALI-INTEGRATION.md](docs/DALI-INTEGRATION.md) — gateway API, and the degraded path
- [docs/INTEGRATION.md](docs/INTEGRATION.md) — the Home Assistant integration
- [CLAUDE.md](CLAUDE.md) — constraints that were expensive to learn, kept where they will be read
