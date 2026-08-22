# Home Assistant integration

Puts the panel fleet in Home Assistant: one device per panel, with its state,
whether it is current, and buttons to reload, sync or restart it.

**Nothing here is required for a panel to work.** Panels pull their config from
the config server directly and run from a cached copy when it is unreachable,
so this integration being broken — or Home Assistant being down — costs
visibility and nothing else. That is the point of the split, and it is worth
keeping.

## Install

Copy `custom_components/pi_panel` into your Home Assistant `config/custom_components/`,
restart, then **Settings → Devices & Services → Add Integration → Pi Panel**.

It asks for three things:

- **Host** — the address *panels* use, normally the Home Assistant host's LAN IP
- **Port** — 8099
- **Admin password** — the add-on's `admin_password`

Use the LAN address, not the sidebar one. Ingress requires Home Assistant's own
authentication and is reachable only from inside HA, so the address you see in
the sidebar is the wrong one here even though it is the obvious one.

## What you get, per panel

| Entity | |
|---|---|
| Online | whether the server has heard from it in the last 90s |
| Home Assistant link | the panel's *own* websocket to HA — separate from the above, and the first thing worth knowing when a panel is up but blank |
| CPU temperature, Disk free, Backlight | from the panel's heartbeat |
| Config version | what the panel reports running |
| Config versions behind | 0 means current; anything else means a push has not landed |
| Agent build | the agent's content hash, comparable with the server's bundle manifest |
| Reload UI / Force sync / Restart panel | commands, allowed under either owner |

## Who owns config

Set in the server's Settings, under **Who owns panel config**:

- `server` — the default. This integration reads and commands, and is refused
  if it tries to write config.
- `homeassistant` — Home Assistant owns it, and the server's config screens go
  read-only with a banner.

The refusal is the point. "Config happens in exactly one place" only holds if
the other place actively says no; otherwise a panel ends up configured half
from each with no way to tell which half is current. Both sides are already
authenticated, so this is a discipline boundary rather than a security one.

Provisioning stays on the server under either setting. Installing hardware is
not Home Assistant's job.

The integration re-reads the setting every poll, so moving ownership in the
server's GUI takes effect without reloading anything here.

## Note for anyone extending this

The client passes `cookie_jar=aiohttp.CookieJar(unsafe=True)`. Do not remove it.
The server authenticates with a cookie and this integration is pointed at an IP
address; aiohttp's default jar refuses to store cookies from a bare IP, so
without it every login succeeds, every cookie is discarded, and every request
afterwards fails as "password rejected" with a perfectly correct password.
