"""Stand-in for a Lunatone DALI-2 IoT gateway.

Implements the endpoints and websocket events the agent uses, to the shapes in
Lunatone's API documentation M0023, so the client can be exercised before the
hardware arrives. Deliberately includes the ambiguity the real thing has: /push
decides whether a level change is announced as a devices event, which is the
open question the agent's poll_s exists for.
"""
import asyncio, json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

app = FastAPI()
SOCKETS: set = set()

DEVICES = {
    1: {"id": 1, "name": "Downlights", "address": 0, "line": 0, "type": "default",
        "features": {"switchable": {"status": False}, "dimmable": {"status": 0},
                     "colorKelvin": {"status": 2700}, "scene": True,
                     "saveToScene": True, "gotoLastActive": {}},
        "scenes": [], "groups": [3], "daliTypes": [8]},
    2: {"id": 2, "name": "Wall wash", "address": 1, "line": 0, "type": "default",
        "features": {"switchable": {"status": True}, "dimmable": {"status": 62},
                     "scene": True, "saveToScene": True, "gotoLastActive": {}},
        "scenes": [], "groups": [3], "daliTypes": []},
}
PUSH = {"on": True}          # whether a control change emits a devices event
SEEN: list = []              # every control request, for assertions


@app.get("/devices")
async def devices():
    return JSONResponse({"devices": list(DEVICES.values()),
                         "timeSignature": {"timestamp": 0, "counter": 1}})


@app.get("/info")
async def info():
    return JSONResponse({"name": "stub-dali-iot", "version": "v1.2.0/1.0.9"})


def _apply(dev, control):
    f = dev["features"]
    if "dimmable" in control:
        f["dimmable"]["status"] = control["dimmable"]
        f["switchable"]["status"] = control["dimmable"] > 0
    if "switchable" in control:
        f["switchable"]["status"] = bool(control["switchable"])
    if "colorKelvin" in control and "colorKelvin" in f:
        f["colorKelvin"]["status"] = control["colorKelvin"]
    if "scene" in control:                       # scenes live in the gear
        f["dimmable"]["status"] = 80 if control["scene"] == 0 else 25
        f["switchable"]["status"] = True


async def _announce(changed):
    if not PUSH["on"]:
        return
    msg = json.dumps({"type": "devices", "data": {"devices": changed},
                      "timeSignature": {"timestamp": 0, "counter": 2}})
    for ws in list(SOCKETS):
        try:
            await ws.send_text(msg)
        except Exception:
            SOCKETS.discard(ws)


@app.post("/broadcast/control")
async def broadcast(body: dict):
    SEEN.append(("broadcast", None, body))
    for d in DEVICES.values():
        _apply(d, body)
    await _announce(list(DEVICES.values()))
    return JSONResponse({})


@app.post("/device/{did}/control")
async def device_control(did: int, body: dict):
    SEEN.append(("device", did, body))
    if did not in DEVICES:
        return JSONResponse({"error": "no such device"}, status_code=404)
    _apply(DEVICES[did], body)
    await _announce([DEVICES[did]])
    return JSONResponse({})


@app.post("/group/{gid}/control")
async def group_control(gid: int, body: dict):
    SEEN.append(("group", gid, body))
    hit = [d for d in DEVICES.values() if gid in d["groups"]]
    for d in hit:
        _apply(d, body)
    await _announce(hit)
    return JSONResponse({})


@app.websocket("/")
async def ws(sock: WebSocket):
    await sock.accept()
    SOCKETS.add(sock)
    await sock.send_text(json.dumps({"type": "info", "data": {"name": "stub-dali-iot"},
                                     "timeSignature": {"timestamp": 0, "counter": 1}}))
    try:
        while True:
            await sock.receive_text()        # the agent sends its filtering frame
    except WebSocketDisconnect:
        pass
    finally:
        SOCKETS.discard(sock)


# --- test controls, not part of the real gateway -------------------------
@app.post("/_push/{on}")
async def set_push(on: int):
    PUSH["on"] = bool(on)
    return {"push": PUSH["on"]}


@app.get("/_seen")
async def seen():
    return {"seen": SEEN}


@app.post("/_bus/{code}")
async def bus(code: int):
    msg = json.dumps({"type": "daliStatus", "data": {"status": code, "line": 0},
                      "timeSignature": {"timestamp": 0, "counter": 3}})
    for s in list(SOCKETS):
        try:
            await s.send_text(msg)
        except Exception:
            SOCKETS.discard(s)
    return {"sent": code}
