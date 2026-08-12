#!/usr/bin/env python3
"""Panel sync agent.

Registers with the config server, heartbeats, and holds a WebSocket so a save
in the GUI arrives immediately. Falls back to polling if the socket drops, and
if the server is unreachable entirely it does nothing at all — the panel keeps
running on the config already on disk. The server is never in the path of a
light turning on.

Install:
  sudo cp panel-agent.py /usr/local/bin/panel-agent
  sudo chmod +x /usr/local/bin/panel-agent
  sudo cp panel-agent.service /etc/systemd/system/
  sudo systemctl enable --now panel-agent
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

SERVER      = os.environ.get("PANEL_SERVER", "http://unraid.local:8099").rstrip("/")
UI_PORT     = int(os.environ.get("PANEL_UI_PORT", "8088"))
PANEL_DIR   = Path(os.environ.get("PANEL_DIR", "/opt/panel"))
CONFIG_PATH = PANEL_DIR / "current" / "config.json"
KIND        = os.environ.get("PANEL_KIND", "pi")
AGENT_VER   = "1.0.0"
POLL_S      = 300
HEARTBEAT_S = 30

HOSTNAME = socket.gethostname()


def _panel_id():
    """Server-issued id, written by the bootstrap script, in preference to the
    hostname. Identity used to be the hostname, which meant renaming a panel
    orphaned its record and it came back as a second, unclaimed device."""
    try:
        v = (PANEL_DIR / "panel-id").read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return HOSTNAME


PANEL_ID = _panel_id()


def mac():
    n = uuid.getnode()
    return ":".join(f"{(n >> i) & 0xff:02x}" for i in range(40, -8, -8))


def ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        a = s.getsockname()[0]
        s.close()
        return a
    except Exception:
        return ""


def local_version():
    try:
        return json.loads(CONFIG_PATH.read_text()).get("_version", 0)
    except Exception:
        return 0


def metrics():
    m = {"ui_version": AGENT_VER}
    try:
        t = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        m["cpu_temp"] = round(int(t) / 1000)
    except Exception:
        pass
    try:
        du = shutil.disk_usage("/")
        m["disk_free"] = f"{round(du.free / du.total * 100)}%"
    except Exception:
        pass
    m["ha_connected"] = UI_STATE["ha_connected"]
    m["pages_open"] = len(PAGES)
    return m


async def write_config(cfg: dict) -> bool:
    """Atomic swap: write beside the live file, fsync, rename over it."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.replace(tmp, CONFIG_PATH)
        print(f"[agent] config v{cfg.get('_version')} written")
        return True
    except Exception as e:
        print(f"[agent] write failed: {e}")
        return False


async def fetch_config(session) -> dict | None:
    try:
        async with session.get(f"{SERVER}/api/config/{PANEL_ID}", timeout=10) as r:
            if r.status == 200:
                return await r.json()
    except Exception:
        pass
    return None


async def sync(client, force=False):
    cfg = await fetch_config(client)
    if not cfg:
        return False
    if not cfg.get("_claimed"):
        print("[agent] not claimed yet")
        return False
    if not force and cfg.get("_version", 0) <= local_version():
        return False
    if await write_config(cfg):
        n = await reload_ui()
        print(f"[agent] reload sent to {n} page(s)")
        return True
    return False


# Sockets held open by the panel UI running in the browser.
PAGES: set = set()
# Reported by the UI over that socket; surfaced in the heartbeat.
UI_STATE = {"ha_connected": False}


async def reload_ui():
    """Tell the page to reload. A real command over a real socket — the old
    `pkill -HUP chromium` was advisory at best and Chromium ignores it."""
    dead = []
    for ws in list(PAGES):
        try:
            await ws.send_json({"type": "reload"})
        except Exception:
            dead.append(ws)
    for ws in dead:
        PAGES.discard(ws)
    return len(PAGES) - len(dead)


async def page_ws(request):
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    PAGES.add(ws)
    print(f"[agent] page connected ({len(PAGES)} open)")
    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except Exception:
                continue
            if data.get("type") == "ha":
                UI_STATE["ha_connected"] = bool(data.get("connected"))
    finally:
        PAGES.discard(ws)
        print(f"[agent] page gone ({len(PAGES)} open)")
    return ws


async def serve_ui():
    """Static server for /opt/panel/current. Required, not optional: Chromium
    blocks fetch() on file:// URLs, so config.json would never load."""
    root = PANEL_DIR / "current"
    root.mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app.router.add_get("/agent", page_ws)
    app.router.add_static("/", str(root), show_index=True)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", UI_PORT).start()
    print(f"[agent] UI served on http://127.0.0.1:{UI_PORT}/panel.html")


def restart_panel():
    subprocess.run(["sudo", "systemctl", "reboot"], check=False)


async def register(session):
    body = {"panel_id": PANEL_ID, "hostname": HOSTNAME, "mac": mac(), "ip": ip(),
            "kind": KIND, "version": AGENT_VER}
    try:
        async with session.post(f"{SERVER}/api/register", json=body, timeout=10) as r:
            if r.status == 200:
                print(f"[agent] registered: {await r.json()}")
                return True
    except Exception as e:
        print(f"[agent] register failed: {e}")
    return False


async def heartbeat_loop(session):
    while True:
        try:
            async with session.post(f"{SERVER}/api/heartbeat", timeout=10, json={
                    "panel_id": PANEL_ID, "metrics": metrics(),
                    "config_version": local_version()}):
                pass
        except Exception:
            pass
        await asyncio.sleep(HEARTBEAT_S)


async def poll_loop(session):
    while True:
        await asyncio.sleep(POLL_S)
        await sync(session)


async def ws_loop(session):
    url = SERVER.replace("http", "ws", 1) + f"/api/ws/{PANEL_ID}"
    while True:
        try:
            async with session.ws_connect(url, heartbeat=20) as ws:
                print("[agent] server socket up")
                await sync(session)
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    t = data.get("type")
                    if t in ("config_updated", "hello", "sync"):
                        await sync(session, force=(t == "sync"))
                    elif t == "reload":
                        await reload_ui()
                    elif t == "restart":
                        restart_panel()
        except Exception as e:
            print(f"[agent] server socket down ({e}); retrying")
        await asyncio.sleep(10)


async def main():
    print(f"[agent] {PANEL_ID} ({HOSTNAME}) -> {SERVER}")
    await serve_ui()                      # start serving immediately: the panel
                                          # must come up even with no server
    # ThreadedResolver rather than aiohttp's default. aiohttp switches to the
    # c-ares AsyncResolver whenever aiodns is importable, and Debian's
    # python3-aiohttp pulls aiodns in. c-ares does pure DNS and never consults
    # NSS, so mDNS stops working: curl resolves a .local server fine while the
    # agent reports "Domain name not found" for the very same host. Installing
    # aiohttp from pip has no aiodns, which is why this worked before apt.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        while not await register(session):
            await asyncio.sleep(15)
        await sync(session)
        await asyncio.gather(ws_loop(session), heartbeat_loop(session), poll_loop(session))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
