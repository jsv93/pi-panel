# Panel Config Server

Self-hosted GUI for configuring and monitoring the wall panel fleet.

**Design rule:** this server is never in the path of a light turning on. Panels
hold their config on disk and keep running if it's unreachable.

## Run it (Unraid / any Docker host)

    cp .env.example .env     # then edit it
    docker compose up -d --build

Then http://<host>:8099 and sign in with `ADMIN_PASSWORD`.

`.env` only has to get you as far as the login screen. Everything below is
editable in **Settings** once you are signed in, stored in the database, and
applied immediately — no recreate, no container access.

| Variable | Purpose |
|---|---|
| `ADMIN_PASSWORD` | GUI login. Change it in Settings; the new one is stored hashed and the env var stops being used. |
| `HA_URL` / `HA_TOKEN` | Only for entity dropdowns and live preview. Never sent to the browser. |

A value set in Settings wins over the environment. Clearing it falls back to
the env var, and the page says which of the two is in force. Settings has a
**Test connection** button that reports the actual HTTP result — use it rather
than guessing at an empty dropdown, which is what a bad URL or token looks
like from the outside.

The env vars are still read at import, so changing *those* needs
`docker compose up -d` rather than `restart`.

Put a copy of `panel.html` in `./data/ui/` so the preview can render it.

Put it behind Caddy for TLS. Tailscale optional but recommended before exposing
anything beyond the LAN.

## Panel side

    sudo cp agent/panel-agent.py /usr/local/bin/panel-agent
    sudo chmod +x /usr/local/bin/panel-agent
    sudo cp agent/panel-agent.service /etc/systemd/system/
    sudo systemctl enable --now panel-agent

Edit `PANEL_SERVER` in the unit file. Layout on the panel:

    /opt/panel/current/panel.html      <- the UI
    /opt/panel/current/config.json     <- written by the agent, synced
    /opt/panel/current/secrets.json    <- {"ha_token": "..."} local only, never synced
(HA connection state is reported by the page to the agent over a local socket.)

The agent serves the UI itself on `127.0.0.1:8088` — `file://` will not work,
because Chromium blocks `fetch()` there and `config.json` would never load.
Point Chromium at:

    http://127.0.0.1:8088/panel.html

Requires `aiohttp` on the panel: `sudo pip3 install aiohttp --break-system-packages`

## Flow

1. Panel boots, agent registers, appears in the GUI as **unclaimed**
2. You Claim it, assign room + template
3. Configure entities in the GUI, hit **Save & push**
4. Server pushes over the panel's WebSocket; the agent writes config atomically
   and sends a reload command to the page over its own local socket
5. Offline panels pick it up on next sync — the GUI flags them as drifted

## Notes

- Configs are versioned; rollback from the Diagnostics section
- **Remove** forgets a device. Live hardware will re-register as unclaimed
- ESP panels register with `kind=esp`; their config is stored and shown, but
  applying it still means an ESPHome recompile
