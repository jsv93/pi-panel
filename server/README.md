# Panel Config Server

Self-hosted GUI for configuring and monitoring the wall panel fleet.

**Design rule:** this server is never in the path of a light turning on. Panels
hold their config on disk and keep running if it's unreachable.

## Run it (Unraid / any Docker host)

    cp .env.example .env     # then edit it
    docker compose up -d --build

Then http://<host>:8099 and sign in with `ADMIN_PASSWORD`.

Set in `.env` (gitignored; `docker-compose.yml` is tracked, so secrets must
not go there). Changing these needs `docker compose up -d`, not `restart` —
they are read once at import:

| Variable | Purpose |
|---|---|
| `ADMIN_PASSWORD` | GUI login. Change it. |
| `HA_URL` / `HA_TOKEN` | Only for entity dropdowns and live preview. Never sent to the browser. |

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
