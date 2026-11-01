"""Opt-in, named, device-scoped diagnostics. No shell or command execution.

Kept separate from the legacy fleet-admin login: that login has a shared
password and HTTP clients that must keep working during migration.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

ROLE = "diagnostics.read"
ABSOLUTE_S = 600
IDLE_S = 120
RESPONSE_S = 10
MAX_SESSIONS = 128
METRICS = frozenset(("ui_version", "cpu_temp", "ram_used_mb", "ram_total_mb",
    "ram_used_pct", "disk_free", "gpu_raster_running", "backlight",
    "browser_health", "browser_heartbeat_age_s", "browser_recoveries_hour",
    "ha_connected", "pages_open", "screen_mode", "bluetooth_active"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Management:
    def __init__(self, db, live, sign):
        self.db, self.live, self.sign = db, live, sign
        self.sessions, self.attempts, self.pending = {}, {}, {}

    def audit(self, event, user="", panel="", outcome="", peer=""):
        # Separate durable store, no payloads, keys, cookies or session tokens.
        path = os.environ.get("PANEL_MANAGEMENT_AUDIT", "/data/management-audit.db")
        try:
            fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(path, timeout=2)) as c, c:
                c.execute("CREATE TABLE IF NOT EXISTS events (at REAL, event TEXT, user TEXT, panel TEXT, outcome TEXT, peer TEXT)")
                c.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                          (time.time(), event, user, panel, outcome, peer))
        except (OSError, sqlite3.Error):
            raise HTTPException(503, "Management audit storage is unavailable")

    def policy(self):
        path = os.environ.get("PANEL_MANAGEMENT_POLICY", "")
        if not path:
            raise HTTPException(503, "Secure diagnostics are not configured")
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 65536:
                raise ValueError()
            cfg = json.loads(raw)
            origin = cfg["origin"]
            u = urlsplit(origin)
            if (u.scheme != "https" or not u.hostname or u.username or u.password
                    or u.path or u.query or u.fragment):
                raise ValueError()
            users = cfg["users"]
            if not isinstance(users, dict) or len(users) > 128:
                raise ValueError()
            for name, p in users.items():
                if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name):
                    raise ValueError()
                if not re.fullmatch(r"[a-f0-9]{64}", p["key_sha256"]):
                    raise ValueError()
                if not isinstance(p["roles"], list) or not isinstance(p["panels"], list):
                    raise ValueError()
                if not all(isinstance(x, str) and 0 < len(x) <= 128 and x != "*"
                           for x in p["roles"] + p["panels"]):
                    raise ValueError()
            return cfg, hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(503, "Management policy is invalid or unavailable")

    def guard(self, request):
        cfg, revision = self.policy()
        # Scheme is supplied by ASGI, never inferred from arbitrary headers here.
        # TLS proxies must have a restricted forwarded-allow-ips configuration.
        if request.url.scheme != "https" or request.headers.get("origin") != cfg["origin"]:
            self.audit("access", outcome="transport_or_origin_denied")
            raise HTTPException(403, "HTTPS and the configured browser origin are required")
        return cfg, revision

    async def body(self, request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 2048:
                raise HTTPException(413, "Request too large")
        try:
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Expected a JSON object")

    def sweep(self):
        now = time.monotonic()
        for key, s in list(self.sessions.items()):
            if now >= s["expires"] or now - s["used"] >= IDLE_S:
                self.audit("session_end", s["user"], s["panel"], "expired", s["peer"])
                self.sessions.pop(key, None)

    async def login(self, request: Request):
        cfg, revision = self.guard(request)
        peer = request.client.host if request.client else "unknown"
        now = time.monotonic()
        self.attempts = {k: v for k, v in self.attempts.items() if now - v[0] < 60}
        start, count = self.attempts.get(peer, (now, 0))
        if count >= 5 or len(self.attempts) >= 1024 and peer not in self.attempts:
            self.audit("login", outcome="rate_limited", peer=peer)
            raise HTTPException(429, "Wait one minute before trying again")
        self.attempts[peer] = (start, count + 1)
        body = await self.body(request)
        name, key, panel = (body.get(k) for k in ("user", "key", "panel"))
        if not all(isinstance(v, str) and len(v) <= 128 for v in (name, key, panel)):
            raise HTTPException(400, "User, access key and panel are required")
        p = cfg["users"].get(name, {})
        valid = hmac.compare_digest(digest(key), p.get("key_sha256", "0" * 64))
        if not valid or ROLE not in p.get("roles", []) or panel not in p.get("panels", []):
            # Only policy-known identities enter the log, never attacker input.
            self.audit("login", name if name in cfg["users"] else "unknown", outcome="denied", peer=peer)
            raise HTTPException(401, "Credentials or device permission refused")
        if not self.db.get_panel(panel):
            raise HTTPException(404, "Panel is not registered")
        self.sweep()
        if len(self.sessions) >= MAX_SESSIONS:
            raise HTTPException(429, "Too many diagnostics sessions")
        token = secrets.token_urlsafe(32)
        self.audit("session_start", name, panel, "allowed", peer)
        self.sessions[digest(token)] = dict(user=name, panel=panel, revision=revision,
            expires=now + ABSOLUTE_S, used=now, last_run=-100., peer=peer)
        return JSONResponse({"session": token, "panel": panel, "expires_in": ABSOLUTE_S,
                             "idle_timeout": IDLE_S}, headers={"Cache-Control": "no-store"})

    def authorize(self, request, panel=None, touch=True):
        cfg, revision = self.guard(request)
        self.sweep()
        header = request.headers.get("authorization", "")
        key = digest(header[7:]) if header.startswith("Bearer ") else ""
        s = self.sessions.get(key)
        if not s:
            self.audit("access", outcome="session_denied")
            raise HTTPException(401, "Diagnostics session expired; sign in again")
        p = cfg["users"].get(s["user"], {})
        if (s["revision"] != revision or ROLE not in p.get("roles", [])
                or s["panel"] not in p.get("panels", [])):
            self.sessions.pop(key, None)
            self.audit("session_end", s["user"], s["panel"], "policy_revoked", s["peer"])
            raise HTTPException(401, "Diagnostics permission changed; sign in again")
        if panel is not None and panel != s["panel"]:
            self.audit("access", s["user"], s["panel"], "wrong_device", s["peer"])
            raise HTTPException(403, "Session is bound to another device")
        if touch:
            s["used"] = time.monotonic()
        return key, s

    async def logout(self, request: Request):
        key, s = self.authorize(request)
        self.audit("session_end", s["user"], s["panel"], "logout", s["peer"])
        self.sessions.pop(key, None)
        return {"ok": True}

    def channel(self, panel):
        ws = self.live.get(panel)
        token = self.db.get_panel_token(panel)
        signing = self.db.get_panel_sign_key(panel)
        if not ws or not token or not signing:
            raise HTTPException(409, "A connected, enrolled panel agent is required")
        if ws.url.scheme != "wss":
            raise HTTPException(409, "The panel agent must reconnect over verified TLS (WSS)")
        if not hmac.compare_digest(ws.headers.get("x-panel-token", ""), token):
            raise HTTPException(409, "Panel credentials changed; reconnect the agent")
        return ws, digest(token + ":" + signing)

    def receive(self, panel, ws, data):
        pending = self.pending.get(panel)
        if not pending or data.get("request_id") != pending["id"] or pending["ws"] is not ws:
            return
        f = pending["future"]
        if f.done():
            return
        try:
            active, credentials = self.channel(panel)
            if active is not ws or credentials != pending["credentials"]:
                raise HTTPException(409, "Panel identity changed during diagnostics")
            if len(json.dumps(data)) > 65536:
                raise HTTPException(502, "Diagnostic response exceeded its limit")
            if data.get("error"):
                raise HTTPException(502, "The panel refused diagnostics")
            raw = data.get("metrics")
            if not isinstance(raw, dict):
                raise HTTPException(502, "Invalid diagnostic response")
            safe = {k: v for k, v in raw.items() if k in METRICS
                    and type(v) in (str, int, float, bool, type(None))
                    and len(str(v)) <= 160}
            f.set_result(safe)
        except HTTPException as e:
            f.set_exception(e)

    async def run(self, panel_id: str, request: Request):
        _, s = self.authorize(request, panel_id)
        body = await self.body(request)
        operation = body.get("operation")
        if set(body) != {"operation"} or operation not in ("connection", "health"):
            self.audit("diagnostic", s["user"], panel_id, "operation_denied", s["peer"])
            raise HTTPException(400, "Choose connection or health; shell commands are unavailable")
        now = time.monotonic()
        if panel_id in self.pending or now - s["last_run"] < 3:
            raise HTTPException(429, "Wait three seconds between diagnostics")
        s["last_run"] = now
        self.audit("diagnostic_start", s["user"], panel_id, operation, s["peer"])
        try:
            p = self.db.get_panel(panel_id)
            if not p:
                raise HTTPException(404, "Panel is not registered")
            if operation == "connection":
                ws = self.live.get(panel_id)
                result = {"panel": panel_id, "agent_connected": bool(ws),
                    "enrolled": bool(self.db.get_panel_token(panel_id) and self.db.get_panel_sign_key(panel_id)),
                    "agent_tls": bool(ws and ws.url.scheme == "wss"),
                    "agent_version": p.get("agent_version"), "last_heartbeat": p.get("last_seen"),
                    "shell_available": False}
            else:
                if not self.db.merged_config(panel_id).get("display", {}).get("remote_diagnostics", True):
                    raise HTTPException(403, "Remote diagnostics are disabled for this panel")
                ws, credentials = self.channel(panel_id)
                request_id = secrets.token_hex(16)
                future = asyncio.get_running_loop().create_future()
                self.pending[panel_id] = dict(id=request_id, ws=ws, future=future, credentials=credentials)
                try:
                    # Existing agents already implement this signed, fixed read.
                    # No screenshot, journal, filename or executable is accepted.
                    await asyncio.wait_for(ws.send_json(self.sign(panel_id, {
                        "type": "screen_diagnostics", "request_id": request_id, "capture": False})), 2)
                    deadline = time.monotonic() + RESPONSE_S
                    while not future.done():
                        await asyncio.wait({future}, timeout=min(0.25, max(0, deadline - time.monotonic())))
                        self.authorize(request, panel_id, touch=False)
                        active, current = self.channel(panel_id)
                        if active is not ws or current != credentials:
                            raise HTTPException(409, "Panel identity changed during diagnostics")
                        if time.monotonic() >= deadline and not future.done():
                            raise HTTPException(504, "Panel diagnostic response timed out")
                    self.authorize(request, panel_id, touch=False)
                    result = {"panel": panel_id, "received_at": time.time(), "metrics": future.result()}
                finally:
                    self.pending.pop(panel_id, None)
                    if not future.done():
                        future.cancel()
            self.audit("diagnostic_end", s["user"], panel_id, "success:" + operation, s["peer"])
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except BaseException as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else "interrupted"
            self.audit("diagnostic_end", s["user"], panel_id, str(status), s["peer"])
            if isinstance(exc, (OSError, RuntimeError, asyncio.TimeoutError)):
                raise HTTPException(503, "Panel connection is unavailable") from None
            raise


def install(app, db, live, sign):
    manager = Management(db, live, sign)
    app.add_api_route("/management/api/session", manager.login, methods=["POST"])
    app.add_api_route("/management/api/logout", manager.logout, methods=["POST"])
    app.add_api_route("/management/api/panels/{panel_id}/diagnostic", manager.run, methods=["POST"])
    directory = Path(__file__).parent / "static" / "management"

    @app.get("/management/")
    async def page():
        return FileResponse(directory / "index.html", headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"})

    @app.get("/management/{asset}")
    async def asset(asset: str):
        if asset not in ("console.js", "console.css"):
            raise HTTPException(404)
        return FileResponse(directory / asset, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return manager
