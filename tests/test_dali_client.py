"""Exercise the agent's gateway client against the stub gateway."""
import asyncio, importlib.util, json, os, sys, types, pathlib

BASE = pathlib.Path(sys.argv[1])
GW = sys.argv[2]

cfgdir = BASE / "dalicfg"
(cfgdir / "current").mkdir(parents=True, exist_ok=True)
os.environ["PANEL_DIR"] = str(cfgdir)

spec = importlib.util.spec_from_file_location(
    "agent", str(pathlib.Path(sys.argv[3])))
ag = importlib.util.module_from_spec(spec)
sys.modules["agent"] = ag
spec.loader.exec_module(ag)

pushed = []
async def fake_tell(payload):
    pushed.append(payload)
ag.tell_pages = fake_tell
ag.DALI_RECONNECT_S = 1


def write_cfg(dali):
    (cfgdir / "current" / "config.json").write_text(
        json.dumps({"_version": 1, "dali": dali}))


import aiohttp

async def gw(method, path, **kw):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, GW + path, **kw) as r:
            return await r.json()


async def main():
    ok = []
    def check(label, got, want):
        good = got == want
        ok.append(good)
        print(("  PASS  " if good else "  FAIL  ") + label)
        if not good:
            print("          got  %r\n          want %r" % (got, want))

    # --- config parsing ---
    write_cfg({"gateway": "", "poll_s": 0})
    check("blank gateway disables", ag._dali_cfg(), None)
    write_cfg({"gateway": "dali-gw.local", "poll_s": 0})
    check("bare host gets http://", ag._dali_cfg(),
          {"url": "http://dali-gw.local", "poll_s": 0})
    write_cfg({"gateway": GW + "/", "poll_s": 5})
    check("trailing slash trimmed, poll kept", ag._dali_cfg(),
          {"url": GW, "poll_s": 5})
    check("ws url derived", ag._dali_ws_url("http://x.local"), "ws://x.local/")

    # --- live against the stub ---
    write_cfg({"gateway": GW, "poll_s": 0})
    task = asyncio.ensure_future(ag.dali_loop())
    await asyncio.sleep(1.5)

    st = ag.dali_public()
    check("connected, cache primed", st["status"], "connected, 2 devices")
    names = sorted(d["name"] for d in st["devices"])
    check("device names", names, ["Downlights", "Wall wash"])
    dt8 = {d["name"]: d["dt8"] for d in st["devices"]}
    check("DT8 detected from daliTypes", dt8,
          {"Downlights": True, "Wall wash": False})

    # dim one device
    okk, detail = await ag.dali_send("device", 1, {"dimmable": 40})
    check("dim device 1 accepted", (okk, detail), (True, ""))
    await asyncio.sleep(0.6)
    d1 = [d for d in ag.dali_public()["devices"] if d["id"] == 1][0]
    check("level tracked from push", (d1["level"], d1["on"]), (40, True))

    seen = (await gw("GET", "/_seen"))["seen"]
    check("gateway got the right body", seen[-1], ["device", 1, {"dimmable": 40}])

    # colour temperature and scene recall
    await ag.dali_send("device", 1, {"colorKelvin": 4000})
    await ag.dali_send("group", 3, {"scene": 0})
    await asyncio.sleep(0.6)
    seen = (await gw("GET", "/_seen"))["seen"]
    check("scene recall targeted the group", seen[-1], ["group", 3, {"scene": 0}])
    d1 = [d for d in ag.dali_public()["devices"] if d["id"] == 1][0]
    check("kelvin tracked", d1["kelvin"], 4000)
    check("scene 0 raised the level", d1["level"], 80)

    # bus power loss is distinct from an unreachable gateway
    await gw("POST", "/_bus/0")
    await asyncio.sleep(0.5)
    check("bus loss reported", ag.dali_public()["bus"], "bus unpowered")
    await gw("POST", "/_bus/2")
    await asyncio.sleep(0.5)
    check("bus recovery clears it", ag.dali_public()["bus"], "")

    # bad input
    okk, detail = await ag.dali_send("nonsense", 1, {"dimmable": 5})
    check("bad target refused", okk, False)

    # gateway disappears
    write_cfg({"gateway": "http://127.0.0.1:9/", "poll_s": 0})
    t0 = asyncio.get_event_loop().time()
    for _ in range(300):
        await asyncio.sleep(0.1)
        if ag.dali_public()["status"].startswith("unreachable:"):
            break
    took = asyncio.get_event_loop().time() - t0
    print("          (noticed after %.1fs)" % took)
    check("unreachable gateway reported within 15s",
          ag.dali_public()["status"].startswith("unreachable:") and took < 15, True)

    # and disabling it clears the cache rather than leaving stale state
    write_cfg({"gateway": "", "poll_s": 0})
    await asyncio.sleep(2.5)
    st = ag.dali_public()
    check("disabling clears state", (st["status"], st["devices"]), ("off", []))

    task.cancel()
    print("\n%d/%d passed" % (sum(ok), len(ok)))
    return 0 if all(ok) else 1


sys.exit(asyncio.get_event_loop().run_until_complete(main()))
