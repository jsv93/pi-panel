"""Panel config server.

Panels register themselves, heartbeat, and hold a WebSocket so a save in the
GUI reaches them immediately. If the socket is down they fall back to polling;
if this server is down entirely they keep running on their cached config.
Nothing here is ever in the path of a light turning on.
"""
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, ha

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
WEAK_DEFAULTS = {"changeme", "change-me", ""}
PBKDF2_ROUNDS = 200_000
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
UI_DIR = os.environ.get("PANEL_UI_DIR", "/data/ui")   # holds panel.html for preview

app = FastAPI(title="Panel Config Server")
db.init()

# panel_id -> WebSocket
LIVE: dict[str, WebSocket] = {}
# session token -> expiry
SESSIONS: dict[str, float] = {}
SESSION_TTL = 60 * 60 * 12


# ---------------------------------------------------------------- auth
def _session_ok(request: Request) -> bool:
    tok = request.cookies.get("psid")
    exp = SESSIONS.get(tok or "")
    return bool(exp and exp > time.time())


def require_admin(request: Request):
    if not _session_ok(request):
        raise HTTPException(status_code=401, detail="not authenticated")
    return True


def _hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def _verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, rounds, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def check_password(pw: str) -> bool:
    """A password set in the GUI is stored hashed and wins. Falling back to the
    env var keeps an existing deployment working before anyone visits Settings."""
    stored = db.get_setting("admin_password_hash")
    if stored:
        return _verify_password(pw, stored)
    return hmac.compare_digest(
        hashlib.sha256(pw.encode()).hexdigest(),
        hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest(),
    )


@app.post("/api/login")
async def login(request: Request, response: Response):
    body = await request.json()
    if not check_password(body.get("password") or ""):
        raise HTTPException(status_code=401, detail="wrong password")
    tok = secrets.token_urlsafe(32)
    SESSIONS[tok] = time.time() + SESSION_TTL
    response.set_cookie("psid", tok, httponly=True, samesite="lax", max_age=SESSION_TTL)
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    SESSIONS.pop(request.cookies.get("psid", ""), None)
    response.delete_cookie("psid")
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request):
    return {"authenticated": _session_ok(request), "ha_configured": ha.configured()}


# ---------------------------------------------------------------- panel-facing
@app.post("/api/register")
async def register(request: Request):
    b = await request.json()
    pid = b.get("panel_id") or b.get("mac") or b.get("hostname")
    if not pid:
        raise HTTPException(400, "panel_id, mac or hostname required")
    p = db.upsert_panel(
        pid, b.get("hostname", pid), b.get("mac"), b.get("ip"),
        b.get("kind", "pi"), b.get("version"),
    )
    return {
        "panel_id": pid,
        "claimed": bool(p["claimed"]),
        "config_version": db.latest_version(pid),
    }


@app.post("/api/heartbeat")
async def heartbeat(request: Request):
    b = await request.json()
    pid = b.get("panel_id")
    if not pid or not db.get_panel(pid):
        raise HTTPException(404, "unknown panel")
    db.touch(pid, b.get("metrics"), b.get("config_version"))
    return {"config_version": db.latest_version(pid)}


@app.get("/api/config/{panel_id}")
async def panel_config(panel_id: str):
    p = db.get_panel(panel_id)
    if not p:
        raise HTTPException(404, "unknown panel")
    cfg = db.merged_config(panel_id)
    cfg["_version"] = db.latest_version(panel_id)
    cfg["_panel_id"] = panel_id
    cfg["_claimed"] = bool(p["claimed"])
    return cfg


@app.websocket("/api/ws/{panel_id}")
async def panel_ws(ws: WebSocket, panel_id: str):
    await ws.accept()
    LIVE[panel_id] = ws
    try:
        await ws.send_json({"type": "hello", "config_version": db.latest_version(panel_id)})
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if data.get("type") == "heartbeat":
                db.touch(panel_id, data.get("metrics"), data.get("config_version"))
                await ws.send_json({"type": "ack", "config_version": db.latest_version(panel_id)})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if LIVE.get(panel_id) is ws:
            LIVE.pop(panel_id, None)


async def notify(panel_id: str, payload: dict):
    ws = LIVE.get(panel_id)
    if not ws:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        LIVE.pop(panel_id, None)
        return False


# ---------------------------------------------------------------- admin API
@app.get("/api/panels", dependencies=[Depends(require_admin)])
async def panels():
    out = db.list_panels()
    for p in out:
        p["live"] = p["id"] in LIVE
    return out


@app.get("/api/panels/{panel_id}", dependencies=[Depends(require_admin)])
async def panel_detail(panel_id: str):
    p = db.get_panel(panel_id)
    if not p:
        raise HTTPException(404, "unknown panel")
    cfg = db.merged_config(panel_id)
    return {
        "panel": p,
        "config": cfg,
        "own": db.get_config(panel_id) or {},
        "history": db.config_history(panel_id),
        "latest_version": db.latest_version(panel_id),
        "problems": await ha.validate_config(cfg),
        "live": panel_id in LIVE,
    }


@app.post("/api/panels/{panel_id}/claim", dependencies=[Depends(require_admin)])
async def claim(panel_id: str, request: Request):
    b = await request.json()
    p = db.claim(panel_id, b.get("room", ""), b.get("template", "default"), b.get("room_label"))
    await notify(panel_id, {"type": "config_updated", "version": db.latest_version(panel_id)})
    return p


@app.put("/api/panels/{panel_id}/config", dependencies=[Depends(require_admin)])
async def put_config(panel_id: str, request: Request):
    if not db.get_panel(panel_id):
        raise HTTPException(404, "unknown panel")
    data = await request.json()
    data.pop("_version", None)
    v = db.save_config(panel_id, data)
    pushed = await notify(panel_id, {"type": "config_updated", "version": v})
    return {"version": v, "pushed": pushed}


@app.post("/api/panels/{panel_id}/rollback", dependencies=[Depends(require_admin)])
async def rollback(panel_id: str, request: Request):
    b = await request.json()
    old = db.get_config(panel_id, int(b["version"]))
    if not old:
        raise HTTPException(404, "no such version")
    old.pop("_version", None)
    v = db.save_config(panel_id, old)
    await notify(panel_id, {"type": "config_updated", "version": v})
    return {"version": v}


@app.post("/api/panels/{panel_id}/action", dependencies=[Depends(require_admin)])
async def action(panel_id: str, request: Request):
    b = await request.json()
    act = b.get("action")
    if act not in ("reload", "restart", "sync"):
        raise HTTPException(400, "unknown action")
    ok = await notify(panel_id, {"type": act})
    return {"sent": ok}


@app.delete("/api/panels/{panel_id}", dependencies=[Depends(require_admin)])
async def remove(panel_id: str):
    """Forget the device. If the hardware is still alive it will re-register
    as unclaimed, which is the intended behaviour — this is 'forget', not 'ban'."""
    db.delete_panel(panel_id)
    ws = LIVE.pop(panel_id, None)
    if ws:
        try:
            await ws.close()
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/push_all", dependencies=[Depends(require_admin)])
async def push_all():
    sent, queued = [], []
    for p in db.list_panels():
        if not p["claimed"]:
            continue
        v = db.latest_version(p["id"])
        if await notify(p["id"], {"type": "config_updated", "version": v}):
            sent.append(p["hostname"])
        else:
            queued.append(p["hostname"])
    return {"sent": sent, "queued": queued}


@app.get("/api/push_all/preview", dependencies=[Depends(require_admin)])
async def push_all_preview():
    rows = []
    for p in db.list_panels():
        if not p["claimed"]:
            continue
        rows.append({
            "hostname": p["hostname"],
            "room": p["room"],
            "online": p["id"] in LIVE,
            "running": p["config_version"],
            "latest": db.latest_version(p["id"]),
        })
    return rows


# ---------------------------------------------------------------- templates
@app.get("/api/templates", dependencies=[Depends(require_admin)])
async def templates():
    return db.list_templates()


@app.get("/api/templates/{name}", dependencies=[Depends(require_admin)])
async def template(name: str):
    t = db.get_template(name)
    if t is None:
        raise HTTPException(404, "no such template")
    return t


@app.put("/api/templates/{name}", dependencies=[Depends(require_admin)])
async def put_template(name: str, request: Request):
    db.save_template(name, await request.json())
    return {"ok": True}


# ---------------------------------------------------------------- HA helpers
@app.get("/api/entities", dependencies=[Depends(require_admin)])
async def entities(domain: str = "", q: str = ""):
    domains = [d for d in domain.split(",") if d] or None
    return await ha.entities(domains, q)


# ---------------------------------------------------------------- settings
@app.get("/api/settings", dependencies=[Depends(require_admin)])
async def get_settings():
    """The token is never returned — only whether one is set and its last four
    characters, which is enough to tell two tokens apart."""
    tok = ha.token()
    return {
        "ha_url": ha.url(),
        "ha_token_set": bool(tok),
        "ha_token_hint": ("…" + tok[-4:]) if tok else "",
        "ha_configured": ha.configured(),
        "ha_last_error": ha.last_error(),
        "sources": ha.source(),
        "admin_password_source": "settings" if db.get_setting("admin_password_hash") else "env",
        "admin_password_is_default": (
            not db.get_setting("admin_password_hash") and ADMIN_PASSWORD in WEAK_DEFAULTS
        ),
        "server": {
            "db_path": db.DB_PATH,
            "ui_dir": UI_DIR,
            "preview_ui_present": os.path.exists(os.path.join(UI_DIR, "panel.html")),
            "session_ttl_hours": round(SESSION_TTL / 3600),
        },
    }


@app.put("/api/settings", dependencies=[Depends(require_admin)])
async def put_settings(request: Request):
    b = await request.json()
    if "ha_url" in b:
        v = (b.get("ha_url") or "").strip().rstrip("/")
        # Clearing removes the row rather than storing "", so the value falls
        # back to the env var and the GUI can honestly say where it came from.
        if v:
            db.set_setting("ha_url", v)
        else:
            db.clear_setting("ha_url")
    if b.get("clear_ha_token"):
        db.clear_setting("ha_token")
    elif (b.get("ha_token") or "").strip():
        db.set_setting("ha_token", b["ha_token"].strip())
    ha.invalidate()
    return await get_settings()


@app.post("/api/settings/test_ha", dependencies=[Depends(require_admin)])
async def test_ha(request: Request):
    """Test before saving, so a bad token can't lock the dropdowns out."""
    b = await request.json()
    return await ha.check((b.get("ha_url") or "").strip(), (b.get("ha_token") or "").strip())


@app.post("/api/settings/password", dependencies=[Depends(require_admin)])
async def set_password(request: Request):
    b = await request.json()
    if not check_password(b.get("current") or ""):
        raise HTTPException(status_code=400, detail="current password is wrong")
    new = b.get("new") or ""
    if len(new) < 8:
        raise HTTPException(status_code=400, detail="new password must be at least 8 characters")
    db.set_setting("admin_password_hash", _hash_password(new))
    # Every other session was authenticated with the old password.
    keep = request.cookies.get("psid", "")
    for t in [t for t in SESSIONS if t != keep]:
        SESSIONS.pop(t, None)
    return {"ok": True}


@app.get("/api/preview/{panel_id}/states", dependencies=[Depends(require_admin)])
async def preview_states(panel_id: str):
    """State for the live preview — proxied so no token reaches the browser."""
    cfg = db.merged_config(panel_id)
    wanted = set()
    for l in cfg.get("lights") or []:
        wanted.add(l.get("entity_id"))
    media = cfg.get("media") or {}
    wanted.add(media.get("default_speaker"))
    for sp in media.get("speakers") or []:
        wanted.add(sp.get("entity_id") if isinstance(sp, dict) else sp)
    sens = cfg.get("sensors") or {}
    wanted.update([sens.get("temperature"), sens.get("humidity")])
    wanted.discard(None); wanted.discard("")
    return [s for s in await ha.states() if s.get("entity_id") in wanted]


# ---------------------------------------------------------------- static
@app.get("/preview/panel.html", dependencies=[Depends(require_admin)])
async def preview_ui():
    path = os.path.join(UI_DIR, "panel.html")
    if not os.path.exists(path):
        return JSONResponse({"error": f"panel.html not found in {UI_DIR}"}, status_code=404)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
