"""Panel tokens, and above all the migration to them.

Reproduces what happens on a real server on the day it is updated: a database
written by a version with no token columns, panels already in it, and agents
from before tokens existed still running. The failure this guards against is
not a leak -- it is locking the fleet out of the update that fixes it.

    python tests/test_panel_tokens.py

Starts its own server on a scratch database; needs fastapi, uvicorn, httpx,
websockets and aiohttp.
"""
import asyncio
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import types

import httpx
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8871
B = f"http://127.0.0.1:{PORT}"
H = {"content-type": "application/json"}

ok_count = [0, 0]


def check(label, got, want):
    good = got == want
    ok_count[0 if good else 1] += 1
    print(("  PASS  " if good else "  FAIL  ") + label)
    if not good:
        print(f"          got  {got!r}\n          want {want!r}")


# ---------------------------------------------------------------- an old database
OLD_SCHEMA = """
CREATE TABLE panels (
    id TEXT PRIMARY KEY, hostname TEXT NOT NULL, mac TEXT, ip TEXT,
    kind TEXT NOT NULL DEFAULT 'pi', agent_version TEXT, room TEXT, template TEXT,
    claimed INTEGER NOT NULL DEFAULT 0, first_seen REAL, last_seen REAL,
    config_version INTEGER NOT NULL DEFAULT 0, metrics TEXT);
CREATE TABLE configs (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_id TEXT NOT NULL,
    version INTEGER NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(panel_id, version));
CREATE TABLE templates (name TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE provisioning (token TEXT PRIMARY KEY, panel_id TEXT NOT NULL,
    created_at REAL NOT NULL, used_at REAL);
"""


def make_old_db(path):
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    now = time.time()
    for pid, host in (("study-1d40", "study-1d40"), ("kitchen-9a2b", "kitchen-9a2b")):
        c.execute("""INSERT INTO panels(id,hostname,kind,claimed,room,template,first_seen,last_seen)
                     VALUES(?,?,'pi',1,?,'default',?,?)""", (pid, host, pid.split('-')[0], now, now))
        c.execute("INSERT INTO configs(panel_id,version,data,created_at) VALUES(?,1,?,?)",
                  (pid, json.dumps({"room_label": pid, "lights": []}), now))
    c.commit()
    c.close()


def load_agent(panel_dir, panel_id):
    os.makedirs(os.path.join(panel_dir, "current"), exist_ok=True)
    open(os.path.join(panel_dir, "panel-id"), "w").write(panel_id)
    os.environ["PANEL_DIR"] = panel_dir
    os.environ["PANEL_SERVER"] = B
    spec = importlib.util.spec_from_file_location(
        "agent_" + panel_id.replace("-", "_"), os.path.join(ROOT, "agent", "panel-agent.py"))
    ag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ag)
    return ag


async def ws_open(pid, token=None):
    hdrs = {"X-Panel-Token": token} if token else {}
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/ws/{pid}",
                                      additional_headers=hdrs, open_timeout=5) as w:
            msg = json.loads(await asyncio.wait_for(w.recv(), 5))
            return msg.get("type")
    except Exception as e:
        return "refused"


async def claim_as(ag, pid):
    """Register the way the agent does when it claims: token and signing key."""
    import aiohttp
    h = dict(ag.server_headers())
    h["X-Panel-Sign-Key"] = ag.SIGN_KEY
    async with aiohttp.ClientSession(headers=h) as s:
        async with s.post(f"{B}/api/register", json={"panel_id": pid}) as r:
            return r.status


def main():
    tmp = tempfile.mkdtemp(prefix="tokens-")
    db = os.path.join(tmp, "panels.db")
    make_old_db(db)
    env = dict(os.environ, PANEL_DB=db, ADMIN_PASSWORD="testpw", PYTHONUNBUFFERED="1")
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=os.path.join(ROOT, "server"), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(50):
            try:
                httpx.get(B + "/api/me", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        run(tmp)
    finally:
        srv.terminate()
        out = srv.communicate(timeout=10)[0]
        print("\n--- server log ---")
        for line in out.splitlines():
            if "[db]" in line or "[server]" in line:
                print("  " + line)
    print(f"\n{ok_count[0]}/{sum(ok_count)} passed")
    return 0 if not ok_count[1] else 1


def run(tmp):
    c = httpx.Client(base_url=B, timeout=10)
    admin = httpx.Client(base_url=B, timeout=10)
    admin.post("/api/login", json={"password": "testpw"})

    print("upgrade day: the database has no token columns")
    cols = [r[1] for r in sqlite3.connect(os.path.join(tmp, "panels.db"))
            .execute("PRAGMA table_info(panels)")]
    check("server added the token columns to the existing table",
          all(x in cols for x in ("token", "token_claimed_at", "token_claimed_from")), True)

    print("\nan agent from before tokens existed -- no header at all")
    pid = "study-1d40"
    check("old agent: register",
          c.post("/api/register", json={"panel_id": pid, "hostname": pid}).status_code, 200)
    check("old agent: heartbeat",
          c.post("/api/heartbeat", json={"panel_id": pid, "metrics": {}}).status_code, 200)
    check("old agent: config", c.get(f"/api/config/{pid}").status_code, 200)
    check("old agent: websocket", asyncio.run(ws_open(pid)), "hello")
    check("old agent: can still fetch the bundle that fixes it",
          c.get("/bundle/manifest").status_code, 200)

    print("\nthe new agent, the real code, claims on first register")
    ag = load_agent(os.path.join(tmp, "panel-study"), pid)
    tokfile = os.path.join(tmp, "panel-study", "panel-token")
    check("agent generated a token", bool(ag.TOKEN) and len(ag.TOKEN) >= 32, True)
    if os.name == "nt":
        # Windows ignores the mode passed to os.open, so this cannot be
        # checked here -- and a pass that is really a skip is worse than a
        # skip, because it gets believed.
        print("  SKIP  token file is mode 600 (POSIX only; the panel is Linux)")
    else:
        check("token file is mode 600", oct(os.stat(tokfile).st_mode & 0o777), "0o600")

    async def agent_register():
        import aiohttp
        async with aiohttp.ClientSession(headers=ag.server_headers()) as s:
            return await ag.register(s)
    check("agent register succeeds", asyncio.run(agent_register()), True)
    d = admin.get(f"/api/panels/{pid}").json()["panel"]
    check("server now shows the panel secured", d.get("secured"), True)
    check("and records where the claim came from", d.get("token_claimed_from"), "127.0.0.1")

    print("\nfrom now on the token is required")
    tok = {"X-Panel-Token": ag.TOKEN}
    bad = {"X-Panel-Token": "x" * 43}
    for label, fn in (
        ("register", lambda h: c.post("/api/register", json={"panel_id": pid}, headers=h)),
        ("heartbeat", lambda h: c.post("/api/heartbeat", json={"panel_id": pid}, headers=h)),
        ("config", lambda h: c.get(f"/api/config/{pid}", headers=h)),
        ("display write", lambda h: c.post(f"/api/panel/{pid}/display",
                                           json={"theme": "ambient"}, headers=h)),
    ):
        check(f"{label}: no token refused", fn({}).status_code, 401)
        check(f"{label}: wrong token refused", fn(bad).status_code, 401)
        check(f"{label}: right token accepted", fn(tok).status_code, 200)
    check("websocket: no token refused", asyncio.run(ws_open(pid)), "refused")
    check("websocket: wrong token refused", asyncio.run(ws_open(pid, "y" * 43)), "refused")
    check("websocket: right token accepted", asyncio.run(ws_open(pid, ag.TOKEN)), "hello")
    check("a secured panel cannot be renamed by someone else",
          c.post("/api/register", json={"panel_id": pid, "hostname": "hijacked"}).status_code, 401)

    print("\nthe other panel is untouched, still in legacy mode")
    check("kitchen, tokenless, still works",
          c.post("/api/heartbeat", json={"panel_id": "kitchen-9a2b"}).status_code, 200)

    print("\nthe token never leaves the server in a panel row")
    fleet = admin.get("/api/panels").json()
    detail = admin.get(f"/api/panels/{pid}").json()
    blob = json.dumps(fleet) + json.dumps(detail)
    check("not in /api/panels or /api/panels/{id}", ag.TOKEN in blob, False)
    check("export does not carry it",
          ag.TOKEN in admin.get(f"/api/panels/{pid}/config/export").text, False)

    print("\nreset reopens the claim, and the panel takes it back unprompted")
    check("admin reset", admin.post(f"/api/panels/{pid}/token/reset").status_code, 200)
    r = c.post("/api/heartbeat", json={"panel_id": pid}, headers=tok)
    check("heartbeat after reset is accepted", r.status_code, 200)
    check("and tells the panel it holds no token", r.json().get("token"), "none")
    # What heartbeat_loop does on "none": the server's signing key went with
    # its token, so the next claim must carry the key again. (Registering
    # without doing this -- the panel-was-off case -- is test_signing.py.)
    ag.CLAIMED_MARK.unlink(missing_ok=True)
    check("the agent re-claims", asyncio.run(agent_register()), True)
    check("secured again", admin.get(f"/api/panels/{pid}").json()["panel"]["secured"], True)

    print("\ntrust on first use: two claims, one winner")
    kid = "kitchen-9a2b"
    # A claim carries a signing key as well as a token (test_signing.py).
    a = {"X-Panel-Token": "A" * 43, "X-Panel-Sign-Key": "a" * 43}
    b = {"X-Panel-Token": "B" * 43, "X-Panel-Sign-Key": "b" * 43}
    first = c.post("/api/register", json={"panel_id": kid}, headers=a)
    second = c.post("/api/register", json={"panel_id": kid}, headers=b)
    check("first claim wins", first.json().get("token"), "claimed")
    check("second is refused", second.status_code, 401)

    print("\nunauthenticated fleet spam is bounded")
    codes = [c.post("/api/register", json={"panel_id": f"ghost{i}"}).status_code
             for i in range(25)]
    check("capped at 20 unclaimed", (codes.count(200), codes.count(429)), (20, 5))

    print("")
    print("a reinstall, which is how this went wrong in the field")
    # A panel claims, then its card is rewritten: /opt/panel/panel-token goes
    # with it, so it comes back with new secrets while the server still holds
    # the old ones. Before, that was register -> 401 every 15s forever, and
    # the GUI said only "offline".
    fresh = load_agent(os.path.join(tmp, "recard"), pid)
    r = c.post("/api/register", json={"panel_id": pid},
               headers={"X-Panel-Token": fresh.TOKEN, "X-Panel-Sign-Key": fresh.SIGN_KEY})
    check("a rebuilt panel is refused", r.status_code, 401)
    d = admin.get(f"/api/panels/{pid}").json()["panel"]
    check("and the server says so, rather than just being offline",
          (d.get("refused") or {}).get("reason"), "a different token")

    # Installing it is the operator saying this hardware is being set up now.
    tok = admin.post(f"/api/panels/{pid}/reprovision").json()["token"]
    check("fetching the bootstrap reopens the claim",
          httpx.get(f"{B}/bootstrap.sh", params={"t": tok}).status_code, 200)
    check("so the rebuilt panel claims", asyncio.run(claim_as(fresh, pid)), 200)
    d = admin.get(f"/api/panels/{pid}").json()["panel"]
    check("secured, and no longer refused", (d.get("secured"), d.get("refused")), (True, None))

    print("\nthe admin endpoint to reset is admin-only")
    check("reset without a session refused",
          c.post(f"/api/panels/{pid}/token/reset").status_code, 401)


if __name__ == "__main__":
    sys.exit(main())
