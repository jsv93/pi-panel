"""Thin Home Assistant REST client.

Used for two things only:
  - enumerating entities so the GUI can offer dropdowns instead of free text
  - proxying state for the live panel preview, so the browser never needs a token

Cached for 30s: the GUI hits this on every form render and HA doesn't need
to be asked that often.
"""
import os
import time

import httpx

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

_cache = {"at": 0, "states": []}
CACHE_S = 30


def configured():
    return bool(HA_URL and HA_TOKEN)


async def states(force=False):
    if not configured():
        return []
    if not force and time.time() - _cache["at"] < CACHE_S:
        return _cache["states"]
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{HA_URL}/api/states", headers=headers)
            r.raise_for_status()
            _cache["states"] = r.json()
            _cache["at"] = time.time()
    except Exception:
        # stale cache beats an error page in the GUI
        pass
    return _cache["states"]


async def entities(domains=None, search=""):
    """[{entity_id, name, domain, state, area}] filtered for the dropdowns."""
    out = []
    for s in await states():
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0] if "." in eid else ""
        if domains and dom not in domains:
            continue
        name = (s.get("attributes") or {}).get("friendly_name") or eid
        if search and search.lower() not in (eid + " " + name).lower():
            continue
        out.append({
            "entity_id": eid,
            "name": name,
            "domain": dom,
            "state": s.get("state"),
        })
    out.sort(key=lambda x: x["name"].lower())
    return out


async def exists(entity_id):
    if not entity_id:
        return True
    return any(s.get("entity_id") == entity_id for s in await states())


async def validate_config(cfg):
    """Return a list of human-readable problems with a config's entity refs."""
    if not configured():
        return []
    known = {s.get("entity_id") for s in await states()}
    problems = []

    def check(eid, label):
        if eid and eid not in known:
            problems.append({"entity_id": eid, "message": f"{label} no longer exists in Home Assistant"})

    for l in cfg.get("lights") or []:
        check(l.get("entity_id"), l.get("name") or l.get("entity_id"))
    media = cfg.get("media") or {}
    check(media.get("default_speaker"), "Default speaker")
    for sp in media.get("speakers") or []:
        check(sp.get("entity_id") if isinstance(sp, dict) else sp, "Speaker")
    sens = cfg.get("sensors") or {}
    check(sens.get("temperature"), "Temperature sensor")
    check(sens.get("humidity"), "Humidity sensor")
    return problems
