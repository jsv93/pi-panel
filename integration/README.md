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

## This integration does not configure panels

It monitors them and issues three commands. Configuration happens on the
server, and the server refuses config writes from here.

There was briefly a setting to hand config ownership to Home Assistant. It was
withdrawn before anyone could use it: turning it on disabled the server's
config screens and gave you nothing to configure with instead, so its only
possible effect was to make things worse.

The enforcement behind it is still in place and still tested — writes from here
are refused with a 409 — so the mode can return the day there is something in
Home Assistant worth owning config with. The obvious candidate is display
settings driven by automations: brightness by time of day, glass tier, the
diagnostics overlay. Those are things the server's GUI genuinely cannot do,
because it has no automation engine, and they would justify the switch. Fleet
monitoring on its own does not.

## What it is good for

Panels fail quietly. A wall panel can be dead for a fortnight before anyone
walks past it. These are the automations worth having:

- **Online** goes off → notify. The panel is down.
- **Home Assistant link** goes off while **Online** stays on → notify. The
  panel is up and showing a blank screen, usually an expired token. From
  across a room those two faults look identical; here they do not.
- **Config versions behind** stays above zero for a few minutes → a push has
  not landed.
- Reload or restart on a schedule, or after something changes.

## Note for anyone extending this

The client passes `cookie_jar=aiohttp.CookieJar(unsafe=True)`. Do not remove it.
The server authenticates with a cookie and this integration is pointed at an IP
address; aiohttp's default jar refuses to store cookies from a bare IP, so
without it every login succeeds, every cookie is discarded, and every request
afterwards fails as "password rejected" with a perfectly correct password.
