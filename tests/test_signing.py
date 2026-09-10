"""Update and config signing -- above all, against a server that is not ours.

The threat is a machine on the LAN answering as the config server. It will
have the panel's token, because the agent sends it on every request; so the
signature must not be something the token can produce. This checks that
directly, then the rest: the signing key crossing the wire exactly once, old
agents still being served, and recovery from a reset -- including a reset
made while the panel was switched off.

    python tests/test_signing.py
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

import aiohttp
import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8873
B = f"http://127.0.0.1:{PORT}"
ok = [0, 0]


def check(label, got, want):
    good = got == want
    ok[0 if good else 1] += 1
    print(("  PASS  " if good else "  FAIL  ") + label)
    if not good:
        print(f"          got  {got!r}\n          want {want!r}")


def load_agent(panel_dir, panel_id):
    os.makedirs(os.path.join(panel_dir, "current"), exist_ok=True)
    open(os.path.join(panel_dir, "panel-id"), "w").write(panel_id)
    os.environ["PANEL_DIR"] = panel_dir
    os.environ["PANEL_SERVER"] = B
    spec = importlib.util.spec_from_file_location(
        f"agent_{time.time_ns()}", os.path.join(ROOT, "agent", "panel-agent.py"))
    ag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ag)
    return ag


def forge(obj, key):
    body = {k: v for k, v in obj.items() if k != "_sig"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {**body, "_sig": hmac.new(key.encode(), canon, hashlib.sha256).hexdigest()}


async def with_session(ag, fn, sent=None):
    """Run fn(session) with the agent's headers, recording every request's
    headers into `sent` if given."""
    trace = aiohttp.TraceConfig()
    if sent is not None:
        async def on_start(_s, _c, p):
            sent.append((str(p.url), dict(p.headers)))
        trace.on_request_start.append(on_start)
    async with aiohttp.ClientSession(headers=ag.server_headers(),
                                     trace_configs=[trace]) as s:
        return await fn(s)


def main():
    tmp = tempfile.mkdtemp(prefix="sign-")
    # A real bundle, so the manifest has files in it to sign.
    bundle = os.path.join(tmp, "bundle")
    os.makedirs(bundle)
    import shutil
    shutil.copy(os.path.join(ROOT, "agent", "panel-agent.py"), bundle)
    shutil.copy(os.path.join(ROOT, "panel-ui", "panel.html"), bundle)
    env = dict(os.environ, PANEL_DB=os.path.join(tmp, "p.db"), PANEL_BUNDLE_DIR=bundle,
               ADMIN_PASSWORD="testpw", PYTHONUNBUFFERED="1")
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
        srv.communicate(timeout=10)
    print(f"\n{ok[0]}/{sum(ok)} passed")
    return 0 if not ok[1] else 1


def run(tmp):
    admin = httpx.Client(base_url=B, timeout=10)
    admin.post("/api/login", json={"password": "testpw"})
    pid = admin.post("/api/provision", json={"room": "Küche"}).json()["panel_id"]

    print("an old agent is still served, unsigned")
    m = httpx.get(B + "/bundle/manifest").json()
    check("manifest without a panel identity has no _sig", "_sig" in m, False)
    check("and still lists the files", "panel-agent.py" in m, True)

    print("\nthe new agent claims, sending its signing key")
    ag = load_agent(os.path.join(tmp, "pk"), pid)
    check("agent has a token and a distinct signing key",
          bool(ag.TOKEN) and bool(ag.SIGN_KEY) and ag.TOKEN != ag.SIGN_KEY, True)
    sent = []
    check("claim succeeds", asyncio.run(with_session(ag, ag.register, sent)), True)
    claim_hdrs = sent[-1][1]
    check("the claim carried the signing key",
          claim_hdrs.get("X-Panel-Sign-Key") == ag.SIGN_KEY, True)
    check("and the panel recorded that it has claimed", ag.CLAIMED_MARK.exists(), True)

    print("\nthe real server's signatures verify")
    cfg = asyncio.run(with_session(ag, ag.fetch_config))
    check("config accepted", isinstance(cfg, dict) and cfg.get("_panel_id") == pid, True)
    check("including a non-ASCII room label, byte-exact", cfg.get("room_label"), "Küche")
    signed_m = httpx.get(B + "/bundle/manifest", params={"panel": pid},
                         headers=ag.server_headers()).json()
    check("a panel that identifies itself gets a signed manifest", "_sig" in signed_m, True)
    check("which the agent accepts", ag.verified(signed_m, "manifest") is not None, True)

    print("\nA SERVER THAT IS NOT OURS -- it has the token, not the key")
    evil_cfg = {**cfg, "connection": {"ha_url": "<img src=x onerror=steal()>"}}
    check("unsigned config refused", ag.verified(evil_cfg, "config"), None)
    check("config signed with the TOKEN refused",
          ag.verified(forge(evil_cfg, ag.TOKEN), "config"), None)
    evil_m = {**{k: v for k, v in signed_m.items() if k != "_sig"},
              "panel-agent.py": {"sha256": "0" * 64, "size": 1}}
    check("manifest signed with the TOKEN refused",
          ag.verified(forge(evil_m, ag.TOKEN), "manifest"), None)
    check("tampered after signing refused",
          ag.verified({**signed_m, "panel-agent.py": {"sha256": "0" * 64, "size": 1}},
                      "manifest"), None)
    check("and a genuine key does verify the same forgery -- the check is real",
          ag.verified(forge(evil_m, ag.SIGN_KEY), "manifest") is not None, True)

    print("\nthe signing key crosses the wire once")
    sent = []

    async def ordinary(s):
        await ag.register(s)
        await ag.fetch_config(s)
        async with s.post(B + "/api/heartbeat", json={"panel_id": pid}):
            pass
        async with s.get(B + "/bundle/manifest", params={"panel": pid}):
            pass
    asyncio.run(with_session(ag, ordinary, sent))
    leaked = [u for u, h in sent if "X-Panel-Sign-Key" in h or ag.SIGN_KEY in json.dumps(h)]
    check(f"{len(sent)} requests after the claim, none carrying the key", leaked, [])
    check("while every one carries the token",
          all(h.get("X-Panel-Token") == ag.TOKEN for _, h in sent), True)

    print("\nthe key never leaves the server either")
    blob = json.dumps(admin.get("/api/panels").json()) + \
        json.dumps(admin.get(f"/api/panels/{pid}").json()) + \
        admin.get(f"/api/panels/{pid}/config/export").text
    check("not in panel rows, detail or export", ag.SIGN_KEY in blob, False)

    print("\na claim must bring a key")
    r = httpx.post(B + "/api/register", json={"panel_id": "loner"},
                   headers={"X-Panel-Token": "T" * 43})
    check("token without a signing key is refused", r.status_code, 400)
    r = httpx.post(B + "/api/register", json={"panel_id": "copycat"},
                   headers={"X-Panel-Token": "T" * 43, "X-Panel-Sign-Key": "T" * 43})
    check("a signing key equal to the token is refused", r.status_code, 400)

    print("\nreset while the panel is running")
    admin.post(f"/api/panels/{pid}/token/reset")
    r = httpx.post(B + "/api/heartbeat", json={"panel_id": pid}, headers=ag.server_headers())
    check("heartbeat reports the reset", r.json().get("token"), "none")
    ag.CLAIMED_MARK.unlink(missing_ok=True)        # what heartbeat_loop does on "none"
    check("re-claim succeeds", asyncio.run(with_session(ag, ag.register)), True)
    # fetch_config returns config only if its signature verified -- it does
    # the checking itself, so a dict back is the pass.
    got = asyncio.run(with_session(ag, ag.fetch_config))
    check("and signatures verify again",
          isinstance(got, dict) and got.get("_panel_id") == pid, True)

    print("\nreset while the panel was switched off -- the case that deadlocked")
    admin.post(f"/api/panels/{pid}/token/reset")
    check("the panel still believes it has claimed", ag.CLAIMED_MARK.exists(), True)
    first = asyncio.run(with_session(ag, ag.register))
    check("so its first register, keyless, is refused", first, False)
    check("which makes it forget that belief", ag.CLAIMED_MARK.exists(), False)
    check("and the next attempt carries the key and claims",
          asyncio.run(with_session(ag, ag.register)), True)
    check("secured again", admin.get(f"/api/panels/{pid}").json()["panel"]["secured"], True)


if __name__ == "__main__":
    sys.exit(main())
