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
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
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
# The agent's own content hash, not a number anyone has to remember to bump --
# which is what "1.0.0" was, unchanged across every release since this file was
# written. It meant the fleet page could not distinguish a panel running last
# week's agent from one running today's, so "did the update land" had no answer
# short of a shell on the panel. The first eight characters match the manifest's
# entry for panel-agent.py, so the two can simply be compared.
def _self_version():
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:8]
    except Exception:
        return "unknown"


AGENT_VER = _self_version()
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


async def nmcli(*args, timeout=20):
    """Run nmcli and return (ok, stdout). Never raises: a panel without
    NetworkManager, or on Ethernet, should degrade to "no wifi" rather than
    taking the agent down with it."""
    try:
        p = await asyncio.create_subprocess_exec(
            "nmcli", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=timeout)
        return p.returncode == 0, out.decode(errors="replace").strip()
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"


def _unescape(field):
    r"""nmcli -t escapes colons inside values as \: — undo that, or an SSID
    containing one is silently truncated at the wrong place."""
    return field.replace("\\:", ":").replace("\\\\", "\\")


def _split_terse(line):
    """Split an nmcli -t line on unescaped colons."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += "\\" + ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(_unescape(cur))
            cur = ""
        else:
            cur += ch
    out.append(_unescape(cur))
    return out


async def wifi_status():
    """How this panel is on the network, and on which wifi if any.

    Reports ethernet as well, because "Network" on the settings page should say
    what is actually carrying traffic. A panel on PoE has no SSID and is not
    disconnected, and showing it as "not connected" would be wrong.
    """
    st = {"available": False, "type": "none", "ssid": "", "signal": 0}

    ok, out = await nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device", "status")
    if ok:
        for line in out.splitlines():
            f = _split_terse(line)
            if len(f) >= 3 and f[2] == "connected":
                if f[1] == "ethernet":
                    st["type"] = "ethernet"
                    break
                if f[1] == "wifi" and st["type"] == "none":
                    st["type"] = "wifi"
        st["available"] = any(_split_terse(l)[1:2] == ["wifi"]
                              for l in out.splitlines() if _split_terse(l))

    ok, out = await nmcli("-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi")
    if ok:
        st["available"] = True
        for line in out.splitlines():
            f = _split_terse(line)
            if len(f) >= 3 and f[0] == "yes":
                st["ssid"], st["signal"] = f[1], _int(f[2])
                break
    return st


def _int(v):
    try:
        return int(v)
    except Exception:
        return 0


async def wifi_scan():
    """Visible networks, strongest first, one entry per SSID."""
    ok, out = await nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi",
                          "list", "--rescan", "yes", timeout=30)
    if not ok:
        return []
    best = {}
    for line in out.splitlines():
        f = _split_terse(line)
        if len(f) < 3 or not f[0]:
            continue
        ssid, sig = f[0], _int(f[1])
        # An SSID appears once per AP; a panel between two of them should see
        # one network, at the better signal.
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": bool(f[2].strip())}
    return sorted(best.values(), key=lambda n: -n["signal"])


GPU_FLAG = "--enable-gpu-rasterization"


def kiosk_gpu():
    """Whether chromium is *running* with GPU rasterisation, and whether the
    launcher on disk asks for it.

    Two answers because they can disagree, and the disagreement is the useful
    part: the launcher is read once, at exec, so an updated launcher and an old
    browser process means the update landed and nothing has restarted yet.
    Reported because the alternative is a shell on a wall panel, and needing one
    to find out whether a flag took is how a release of flags went unnoticed on
    two panels for a week.
    """
    disk = running = False
    try:
        disk = GPU_FLAG in Path("/usr/local/bin/panel-kiosk-launch").read_text()
    except Exception:
        pass
    try:
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                cmd = (p / "cmdline").read_bytes().decode("utf-8", "replace")
            except Exception:
                continue
            if "chromium" not in cmd or "--type=" in cmd:
                continue          # skip the renderer/gpu helper processes
            running = GPU_FLAG in cmd
            break
    except Exception:
        pass
    return {"gpu_raster_running": running, "gpu_raster_on_disk": disk}


def metrics():
    m = {"ui_version": AGENT_VER}
    m.update(kiosk_gpu())
    m.update(UI_STATE.get("wifi") or {})
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


# Where each bundle file lives on a panel, and what to do once it changes.
BUNDLE_TARGETS = {
    "panel.html":     Path("/opt/panel/current/panel.html"),
    "panel-agent.py": Path("/usr/local/bin/panel-agent"),
    "backlight.py":   Path("/usr/local/bin/panel-backlight"),
    # Here because it was not: the launcher is written once at install time, so
    # a chromium flag added to it reached a panel only on a full reinstall.
    "kiosk-launch.sh": Path("/usr/local/bin/panel-kiosk-launch"),
}
SELF = "panel-agent.py"
PREV = Path("/usr/local/bin/panel-agent.prev")
PENDING = PANEL_DIR / "update-pending"


def sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


async def fetch_bundle(session, name, digest):
    """Download one file, verify it, and put it in place atomically.

    Verified against the manifest before it replaces anything: a truncated
    download that still parses would otherwise be installed and, in the agent's
    case, restarted into.
    """
    target = BUNDLE_TARGETS[name]
    try:
        async with session.get(f"{SERVER}/bundle/{name}", timeout=60) as r:
            if r.status != 200:
                return False
            data = await r.read()
    except Exception as e:
        print(f"[agent] update {name}: fetch failed: {e}")
        return False

    if hashlib.sha256(data).hexdigest() != digest:
        print(f"[agent] update {name}: hash mismatch, ignoring")
        return False

    tmp = target.with_suffix(target.suffix + ".new")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        # A syntax error here would restart-loop the agent forever, or in the
        # launcher's case leave a black screen, and on a wall panel neither is
        # something to discover later.
        check = None
        if name.endswith(".py"):
            check = [sys.executable, "-m", "py_compile", str(tmp)]
        elif name.endswith(".sh"):
            check = ["sh", "-n", str(tmp)]
        if check:
            r = subprocess.run(check, capture_output=True)
            if r.returncode != 0:
                print(f"[agent] update {name}: does not parse, ignoring")
                tmp.unlink(missing_ok=True)
                return False
            tmp.chmod(0o755)
        if name == SELF and target.exists():
            shutil.copy2(target, PREV)     # something to fall back to
        os.replace(tmp, target)
        print(f"[agent] update {name}: installed")
        return True
    except Exception as e:
        print(f"[agent] update {name}: install failed: {e}")
        tmp.unlink(missing_ok=True)
        return False


async def check_bundle(session):
    """Pull any bundle file whose hash differs from the server's.

    This is what makes a server update reach a panel at all: these files are
    fetched once during provisioning and never again otherwise.
    """
    try:
        async with session.get(f"{SERVER}/bundle/manifest", timeout=15) as r:
            if r.status != 200:
                return
            manifest = await r.json()
    except Exception:
        return

    changed, self_changed = [], False
    for name, info in manifest.items():
        target = BUNDLE_TARGETS.get(name)
        if not target or sha256(target) == info.get("sha256"):
            continue
        if await fetch_bundle(session, name, info["sha256"]):
            changed.append(name)
            self_changed = self_changed or name == SELF

    if not changed:
        return
    if "panel.html" in changed:
        await reload_ui()
    if "backlight.py" in changed:
        subprocess.run(["systemctl", "restart", "panel-backlight"], check=False)
    if "kiosk-launch.sh" in changed:
        # Chromium reads its flags once, at exec. Restarting the unit takes the
        # browser down and back up -- visible on the wall for a second, and the
        # only way a launcher change means anything.
        print("[agent] kiosk launcher changed, restarting cage-kiosk")
        subprocess.run(["systemctl", "restart", "cage-kiosk"], check=False)
    if self_changed:
        # Leave a marker and exit; systemd restarts us. The replacement checks
        # for the marker and rolls back if it cannot reach the server, so a bad
        # agent cannot strand a panel.
        try:
            PENDING.write_text(str(time.time()))
        except Exception:
            pass
        print("[agent] update: restarting into the new agent")
        os._exit(0)


async def confirm_update(session):
    """Called once after a self-update, from the new agent.

    Registering is the test: it exercises config, network and the server, which
    is everything the agent is for. Failing that, put the old one back rather
    than leaving a panel that cannot be managed.
    """
    if not PENDING.exists():
        PREV.unlink(missing_ok=True)
        return
    for _ in range(12):
        if await register(session):
            print("[agent] update: confirmed")
            PENDING.unlink(missing_ok=True)
            PREV.unlink(missing_ok=True)
            return
        await asyncio.sleep(5)
    if PREV.exists():
        print("[agent] update: could not reach the server, rolling back")
        shutil.copy2(PREV, BUNDLE_TARGETS[SELF])
        PREV.unlink(missing_ok=True)
    PENDING.unlink(missing_ok=True)
    os._exit(0)


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
    # Not `<=`. A lower version on the server does not mean "we are ahead", it
    # means the record was replaced -- re-provisioning issues a new panel id
    # whose config starts at version 1, while the config on disk may be at 5.
    # Treating that as up to date leaves the panel showing the old room's
    # lights forever and silently ignoring every future push.
    if not force and cfg.get("_version", 0) == local_version():
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
            elif data.get("type") == "viewport":
                # A panel has no console, so what the page measured is only
                # visible if it says so somewhere readable over SSH.
                print(f"[agent] viewport {json.dumps({k: v for k, v in data.items() if k != 'type'})}")
    finally:
        PAGES.discard(ws)
        print(f"[agent] page gone ({len(PAGES)} open)")
    return ws


async def wifi_get(request):
    """Status plus, if asked, a scan. Scanning takes seconds, so the panel's
    settings sheet asks for it only when someone opens the wifi list."""
    body = {"status": await wifi_status()}
    if request.query.get("scan") == "1":
        body["networks"] = await wifi_scan()
    return web.json_response(body)


async def wifi_connect(request):
    """Join a network.

    Deliberately here and not on the config server: a panel with broken wifi
    is exactly the panel the server cannot reach, so server-side wifi config
    would only work when it was not needed. It also keeps network credentials
    off the server, and means whoever changes a setting that can cut the panel
    off is standing in front of it.
    """
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    ssid = (b.get("ssid") or "").strip()
    if not ssid:
        return web.json_response({"ok": False, "error": "ssid required"}, status=400)
    psk = b.get("psk") or ""
    args = ["device", "wifi", "connect", ssid]
    if psk:
        args += ["password", psk]
    ok, out = await nmcli(*args, timeout=45)
    # nmcli reports a wrong key as a plain failure; pass its own words through
    # rather than inventing a friendlier message that says less.
    return web.json_response({"ok": ok, "message": out,
                              "status": await wifi_status()})


async def serve_ui():
    """Static server for /opt/panel/current. Required, not optional: Chromium
    blocks fetch() on file:// URLs, so config.json would never load."""
    root = PANEL_DIR / "current"
    root.mkdir(parents=True, exist_ok=True)

    @web.middleware
    async def no_cache(request, handler):
        """Nothing served here may be cached.

        With no cache headers the browser applies heuristic freshness and stops
        revalidating entirely — so a replaced panel.html or a freshly synced
        config.json is simply not fetched, and the panel goes on showing the
        old one with nothing to indicate why. Chromium here has a persistent
        profile, so that cache survives restarts and reboots too.
        """
        resp = await handler(request)
        try:
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
        except Exception:
            pass          # websocket responses are already sent
        return resp

    app = web.Application(middlewares=[no_cache])
    app.router.add_get("/agent", page_ws)
    # Before the static catch-all, which would otherwise swallow these.
    app.router.add_get("/wifi", wifi_get)
    app.router.add_post("/wifi/connect", wifi_connect)
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
        # Refreshed here rather than inside metrics(), which is synchronous and
        # called from places that must not block on a subprocess.
        try:
            st = await wifi_status()
            UI_STATE["wifi"] = ({"wifi_ssid": st.get("ssid", ""),
                                 "wifi_signal": st.get("signal", 0)}
                                if st.get("available") and st.get("ssid") else {})
        except Exception:
            pass
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
        # Same cadence as config: a panel that has been up for weeks should not
        # need anyone to remember it exists.
        await check_bundle(session)


async def ws_loop(session):
    url = SERVER.replace("http", "ws", 1) + f"/api/ws/{PANEL_ID}"
    while True:
        try:
            async with session.ws_connect(url, heartbeat=20) as ws:
                print("[agent] server socket up")
                await sync(session)
                # The socket drops when the server restarts, and the server
                # restarts when it is updated -- which is exactly when there is
                # a new bundle to collect. Checking on reconnect turns "up to
                # five minutes" into "seconds" for the case that matters.
                await check_bundle(session)
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    t = data.get("type")
                    if t in ("config_updated", "hello", "sync"):
                        await sync(session, force=(t == "sync"))
                        # Force sync means "catch up with the server", which
                        # people reasonably read as including the panel's own
                        # files. It did not, so the button appeared to do
                        # nothing whenever the bundle was what had changed.
                        if t == "sync":
                            await check_bundle(session)
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
        # Before anything else: if this process is a just-installed agent,
        # prove it works or put the old one back.
        await confirm_update(session)
        while not await register(session):
            await asyncio.sleep(15)
        await sync(session)
        await check_bundle(session)
        await asyncio.gather(ws_loop(session), heartbeat_loop(session), poll_loop(session))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
