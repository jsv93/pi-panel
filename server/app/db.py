"""SQLite storage for the panel fleet.

Deliberately plain: one file, no ORM. Panels, their configs (versioned so
rollback is possible), and reusable templates.
"""
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("PANEL_DB", "/data/panels.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS panels (
    id              TEXT PRIMARY KEY,
    hostname        TEXT NOT NULL,
    mac             TEXT,
    ip              TEXT,
    kind            TEXT NOT NULL DEFAULT 'pi',   -- 'pi' | 'esp'
    agent_version   TEXT,
    room            TEXT,
    template        TEXT,
    claimed         INTEGER NOT NULL DEFAULT 0,
    first_seen      REAL,
    last_seen       REAL,
    config_version  INTEGER NOT NULL DEFAULT 0,   -- version the panel reports running
    metrics         TEXT                          -- JSON blob from heartbeat
);

CREATE TABLE IF NOT EXISTS configs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id   TEXT NOT NULL,
    version    INTEGER NOT NULL,
    data       TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(panel_id, version)
);

CREATE TABLE IF NOT EXISTS templates (
    name       TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Server settings edited from the GUI. Env vars remain the bootstrap default
-- so an existing deployment keeps working; anything set here wins over them.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- One-time tokens binding a physical Pi to a panel record created in the GUI
-- before the hardware exists. Consumed when the bootstrap script is fetched.
CREATE TABLE IF NOT EXISTS provisioning (
    token      TEXT PRIMARY KEY,
    panel_id   TEXT NOT NULL,
    created_at REAL NOT NULL,
    used_at    REAL
);
"""

DEFAULT_TEMPLATE = {
    "room_label": "Room",
    "lights": [],
    "media": {"default_speaker": "", "default_speaker_name": "", "speakers": []},
    "sensors": {"temperature": "", "humidity": ""},
    "display": {
        "idle_timeout_s": 45,
        "backlight_default": 100,
        "backlight_min": 5,
        # Seconds after going idle before the backlight is blanked outright.
        # 0 = never; dimming alone still glows noticeably on this panel.
        "backlight_off_s": 0,
        "glass_tier": 0,
        # Visual theme. "default" is the build as shipped; "ambient" is the
        # warm, borderless one. A theme changes only appearance -- every
        # measurement and every control is the same in both.
        "theme": "default",
        # dtoverlay line for the panel's DSI display, written to config.txt at
        # provisioning. Stock Raspberry Pi OS auto-detects only the official
        # Touch Display, so a third-party panel with the wrong line here gets
        # no signal at all. Empty means add nothing, which is correct for the
        # official display.
        "dsi_overlay": "vc4-kms-dsi-waveshare-panel-v2,5_0_inch_a",
        # Connection status and frame counter on the panel. Bring-up tools; a
        # finished panel on a wall should not be showing a frame counter.
        "diagnostics": False,
        # Only needed where the browser misreports the panel's size. Chromium
        # will not report a viewport narrower than ~500px, so a 480-wide panel
        # is told it is 500 and anything scaled to that overflows. 0 = trust
        # the browser.
        "screen_width": 0,
        "screen_height": 0,
    },
    "connection": {"ha_url": "http://homeassistant.local:8123"},
}


@contextmanager
def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        row = c.execute("SELECT 1 FROM templates WHERE name='default'").fetchone()
        if not row:
            c.execute(
                "INSERT INTO templates(name,data,updated_at) VALUES(?,?,?)",
                ("default", json.dumps(DEFAULT_TEMPLATE), time.time()),
            )


# ---------------------------------------------------------------- panels
def upsert_panel(panel_id, hostname, mac, ip, kind, agent_version):
    now = time.time()
    with conn() as c:
        row = c.execute("SELECT id FROM panels WHERE id=?", (panel_id,)).fetchone()
        if row:
            c.execute(
                """UPDATE panels SET hostname=?, mac=?, ip=?, kind=?, agent_version=?,
                   last_seen=? WHERE id=?""",
                (hostname, mac, ip, kind, agent_version, now, panel_id),
            )
        else:
            c.execute(
                """INSERT INTO panels(id,hostname,mac,ip,kind,agent_version,claimed,
                   first_seen,last_seen) VALUES(?,?,?,?,?,?,0,?,?)""",
                (panel_id, hostname, mac, ip, kind, agent_version, now, now),
            )
    return get_panel(panel_id)


def _panel_row(r):
    """One row, with metrics as an object rather than the JSON text it is
    stored as.

    Here because list_panels() parsed that column and get_panel() did not, so
    the fleet page showed a panel's metrics while the detail page -- reading the
    same column through the other function -- showed an em dash for every field,
    forever. Nothing errored: JavaScript reading .cpu_temp off a string just
    gets undefined. It cost a long hunt for an agent that was not reporting,
    through a readout that could not have displayed the report.
    """
    d = dict(r)
    try:
        d["metrics"] = json.loads(d["metrics"]) if d["metrics"] else {}
    except Exception:
        d["metrics"] = {}
    return d


def get_panel(panel_id):
    with conn() as c:
        r = c.execute("SELECT * FROM panels WHERE id=?", (panel_id,)).fetchone()
        return _panel_row(r) if r else None


def list_panels():
    with conn() as c:
        rows = c.execute("SELECT * FROM panels ORDER BY claimed DESC, hostname").fetchall()
    out = []
    for r in rows:
        d = _panel_row(r)
        d["latest_version"] = latest_version(d["id"])
        d["online"] = bool(d["last_seen"] and (time.time() - d["last_seen"]) < 90)
        out.append(d)
    return out


def touch(panel_id, metrics, config_version):
    with conn() as c:
        c.execute(
            "UPDATE panels SET last_seen=?, metrics=?, config_version=? WHERE id=?",
            (time.time(), json.dumps(metrics or {}), config_version or 0, panel_id),
        )


def claim(panel_id, room, template, room_label=None):
    with conn() as c:
        c.execute(
            "UPDATE panels SET claimed=1, room=?, template=? WHERE id=?",
            (room, template or "default", panel_id),
        )
    cfg = merged_config(panel_id)
    cfg["room_label"] = room_label or room or cfg.get("room_label", "Room")
    save_config(panel_id, cfg)
    return get_panel(panel_id)


def delete_panel(panel_id):
    with conn() as c:
        c.execute("DELETE FROM configs WHERE panel_id=?", (panel_id,))
        c.execute("DELETE FROM panels WHERE id=?", (panel_id,))


# ---------------------------------------------------------------- configs
def latest_version(panel_id):
    with conn() as c:
        r = c.execute(
            "SELECT MAX(version) v FROM configs WHERE panel_id=?", (panel_id,)
        ).fetchone()
    return r["v"] or 0


def save_config(panel_id, data):
    v = latest_version(panel_id) + 1
    with conn() as c:
        c.execute(
            "INSERT INTO configs(panel_id,version,data,created_at) VALUES(?,?,?,?)",
            (panel_id, v, json.dumps(data), time.time()),
        )
    return v


def get_config(panel_id, version=None):
    with conn() as c:
        if version:
            r = c.execute(
                "SELECT * FROM configs WHERE panel_id=? AND version=?", (panel_id, version)
            ).fetchone()
        else:
            r = c.execute(
                "SELECT * FROM configs WHERE panel_id=? ORDER BY version DESC LIMIT 1",
                (panel_id,),
            ).fetchone()
    if not r:
        return None
    d = json.loads(r["data"])
    d["_version"] = r["version"]
    return d


def config_history(panel_id, limit=10):
    with conn() as c:
        rows = c.execute(
            "SELECT version, created_at FROM configs WHERE panel_id=? ORDER BY version DESC LIMIT ?",
            (panel_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def merged_config(panel_id):
    """Template values, overlaid with whatever this panel overrides."""
    p = get_panel(panel_id) or {}
    tpl = get_template(p.get("template") or "default") or DEFAULT_TEMPLATE
    own = get_config(panel_id) or {}
    own.pop("_version", None)
    return deep_merge(tpl, own)


# ---------------------------------------------------------------- provisioning
def slug(s):
    out = "".join(c.lower() if c.isalnum() else "-" for c in (s or ""))
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "panel"


def create_provisional_panel(room, template, room_label=None):
    """Create the panel record before the hardware exists.

    The id is issued here rather than taken from the Pi's hostname: hostname
    identity is why renaming a panel used to orphan its record. The agent
    writes this id to disk and prefers it forever after.
    """
    panel_id = f"{slug(room)}-{secrets.token_hex(2)}"
    now = time.time()
    with conn() as c:
        c.execute(
            """INSERT INTO panels(id,hostname,kind,claimed,room,template,
               first_seen,last_seen) VALUES(?,?,?,1,?,?,?,NULL)""",
            (panel_id, panel_id, "pi", room, template or "default", now),
        )
    cfg = merged_config(panel_id)
    cfg["room_label"] = room_label or room or cfg.get("room_label", "Room")
    save_config(panel_id, cfg)
    return panel_id


def create_token(panel_id):
    token = secrets.token_urlsafe(16)
    with conn() as c:
        c.execute(
            "INSERT INTO provisioning(token,panel_id,created_at) VALUES(?,?,?)",
            (token, panel_id, time.time()),
        )
    return token


def clear_tokens(panel_id):
    """Drop a panel's unused tokens.

    Issuing a second one without this leaves both valid, and whichever the GUI
    happened to show first is not necessarily the one someone runs.
    """
    with conn() as c:
        c.execute("DELETE FROM provisioning WHERE panel_id=? AND used_at IS NULL",
                  (panel_id,))


def consume_token(token):
    """Return the panel_id for an unused token and mark it spent, else None."""
    with conn() as c:
        r = c.execute(
            "SELECT panel_id FROM provisioning WHERE token=? AND used_at IS NULL",
            (token,),
        ).fetchone()
        if not r:
            return None
        c.execute("UPDATE provisioning SET used_at=? WHERE token=?", (time.time(), token))
    return r["panel_id"]


def pending_tokens():
    """Unused tokens, so the GUI can re-show a command for a panel not yet built."""
    with conn() as c:
        rows = c.execute(
            """SELECT p.token, p.panel_id, p.created_at, n.room
               FROM provisioning p LEFT JOIN panels n ON n.id = p.panel_id
               WHERE p.used_at IS NULL ORDER BY p.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- settings
def get_setting(key, default=""):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key, value):
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, time.time()),
        )


def clear_setting(key):
    with conn() as c:
        c.execute("DELETE FROM settings WHERE key=?", (key,))


# ---------------------------------------------------------------- templates
def get_template(name):
    with conn() as c:
        r = c.execute("SELECT data FROM templates WHERE name=?", (name,)).fetchone()
    return json.loads(r["data"]) if r else None


def list_templates():
    with conn() as c:
        rows = c.execute("SELECT name, updated_at FROM templates ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def save_template(name, data):
    with conn() as c:
        c.execute(
            "INSERT INTO templates(name,data,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (name, json.dumps(data), time.time()),
        )
