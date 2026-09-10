"""Login rate limiting: per address, bounding how much hashing one can force.

    python tests/test_login_limits.py

Starts its own server on a scratch database. The per-address check connects
from 127.0.0.2, which routes to loopback on both Linux and Windows.
"""
import os
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8872
B = f"http://127.0.0.1:{PORT}"
ok = [0, 0]


def check(label, got, want):
    good = got == want
    ok[0 if good else 1] += 1
    print(("  PASS  " if good else "  FAIL  ") + label)
    if not good:
        print(f"          got  {got!r}\n          want {want!r}")


def login(pw, client=None):
    c = client or httpx.Client(base_url=B, timeout=30)
    return c.post("/api/login", json={"password": pw})


def main():
    tmp = tempfile.mkdtemp(prefix="login-")
    env = dict(os.environ, PANEL_DB=os.path.join(tmp, "p.db"),
               ADMIN_PASSWORD="right-password", PYTHONUNBUFFERED="1")
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
        run()
    finally:
        srv.terminate()
        srv.communicate(timeout=10)
    print(f"\n{ok[0]}/{sum(ok)} passed")
    return 0 if not ok[1] else 1


def run():
    print("the lockout")
    codes = [login(f"guess{i}").status_code for i in range(5)]
    check("first five wrong passwords: plain refusals", codes, [401] * 5)
    r = login("guess6")
    check("sixth: locked out", r.status_code, 429)
    check("with a Retry-After", bool(r.headers.get("retry-after")), True)
    check("and while locked, even the RIGHT password is refused",
          login("right-password").status_code, 429)

    print("\nper address -- a lockout on one machine is not a lockout for everyone")
    try:
        other = httpx.Client(base_url=B, timeout=30,
                             transport=httpx.HTTPTransport(local_address="127.0.0.2"))
        check("another address can still sign in",
              login("right-password", other).status_code, 200)
    except Exception as e:
        print(f"  SKIP  per-address check (cannot bind 127.0.0.2 here: {e})")

    print("\nthe lockout bounds how much hashing one address can force")
    # A stored password is PBKDF2 at 200k rounds -- the expensive path. Set one
    # from a clean address so the lockout above is not in the way.
    admin = httpx.Client(base_url=B, timeout=30,
                         transport=httpx.HTTPTransport(local_address="127.0.0.3"))
    check("sign in from a clean address", login("right-password", admin).status_code, 200)
    check("set a GUI password (stored as PBKDF2)",
          admin.post("/api/settings/password",
                     json={"current": "right-password", "new": "a-better-password"}).status_code,
          200)

    # The cost of one checked attempt, as the median of three wrong passwords
    # on a warm connection. Timing a single first request instead measures
    # connection setup as much as hashing -- it came out four times too high,
    # which made the assertion below pass whether or not the lockout worked.
    probe = httpx.Client(base_url=B, timeout=30,
                         transport=httpx.HTTPTransport(local_address="127.0.0.4"))
    probe.get("/api/me")
    samples = []
    for i in range(3):
        t = time.perf_counter()
        probe.post("/api/login", json={"password": f"probe{i}"})
        samples.append(time.perf_counter() - t)
    one_hash = sorted(samples)[1]
    print(f"          (one checked attempt: {one_hash*1000:.0f}ms)")

    # What this does NOT test: that a hash leaves the event loop free. It was
    # tested, and on this build it does not -- pbkdf2_hmac held the GIL, four
    # threads taking 3.2x as long as one on 24 cores -- so moving it to a
    # thread buys nothing here. What bounds an attack is the lockout, and
    # that is what is checked: twenty wrong passwords from ONE address cost
    # about five hashes, because the other fifteen are refused before any
    # hashing happens.
    flood = httpx.Client(base_url=B, timeout=60,
                         transport=httpx.HTTPTransport(local_address="127.0.0.5"))
    flood.get("/api/me")
    t = time.perf_counter()
    codes = [flood.post("/api/login", json={"password": f"w{i}"}).status_code
             for i in range(20)]
    took = time.perf_counter() - t
    print(f"          (20 attempts from one address: {took*1000:.0f}ms)")
    check("only five were ever checked", (codes.count(401), codes.count(429)), (5, 15))
    # Unlimited, twenty checked attempts cost ~20 hashes. Limited, ~5. Ten is
    # the line between them, with room either side for timing noise.
    check("so the flood cost about five hashes' time, not twenty",
          took < one_hash * 10, True)

    print("\npassword change has the same limit")
    pc = httpx.Client(base_url=B, timeout=30,
                      transport=httpx.HTTPTransport(local_address="127.0.0.6"))
    check("sign in", login("a-better-password", pc).status_code, 200)
    tries = [pc.post("/api/settings/password",
                     json={"current": f"nope{i}", "new": "zzzzzzzzzz"}).status_code
             for i in range(7)]
    check("five wrong current-passwords, then locked", tries, [400] * 5 + [429] * 2)


if __name__ == "__main__":
    sys.exit(main())
