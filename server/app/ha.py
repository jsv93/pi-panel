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

from . import db

_cache = {"at": 0, "states": []}
CACHE_S = 30

# Why the last failure is kept: a swallowed exception here shows up as empty
# entity dropdowns and nothing else, which is indistinguishable from "HA has
# no entities". The settings page surfaces this instead of leaving it silent.
_last_error = ""


def url():
    """Stored setting wins; env is the bootstrap default for a fresh deploy."""
    return (db.get_setting("ha_url") or os.environ.get("HA_URL", "")).rstrip("/")


def token():
    return db.get_setting("ha_token") or os.environ.get("HA_TOKEN", "")


def source():
    """Where each value is coming from, so the GUI can say so."""
    return {
        "ha_url": "settings" if db.get_setting("ha_url") else ("env" if os.environ.get("HA_URL") else "unset"),
        "ha_token": "settings" if db.get_setting("ha_token") else ("env" if os.environ.get("HA_TOKEN") else "unset"),
    }


def configured():
    return bool(url() and token())


def last_error():
    return _last_error


def invalidate():
    """Drop the cache so a settings change takes effect on the next request."""
    _cache["at"] = 0
    _cache["states"] = []


async def check(test_url="", test_token=""):
    """Live credential test. Takes explicit values so the GUI can verify before
    saving. Returns a dict rather than raising — the caller renders it."""
    u = (test_url or url()).rstrip("/")
    t = test_token or token()
    if not u or not t:
        return {"ok": False, "error": "URL and token are both required"}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{u}/api/states", headers={"Authorization": f"Bearer {t}"})
    except Exception as e:
        return {"ok": False, "error": f"cannot reach {u}: {e.__class__.__name__}"}
    if r.status_code == 401:
        return {"ok": False, "status": 401, "error": "token rejected"}
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "error": r.text[:200]}
    try:
        return {"ok": True, "status": 200, "entities": len(r.json())}
    except Exception:
        return {"ok": False, "status": 200, "error": "response was not JSON — is this a Home Assistant URL?"}


async def states(force=False):
    global _last_error
    if not configured():
        return []
    if not force and time.time() - _cache["at"] < CACHE_S:
        return _cache["states"]
    headers = {"Authorization": f"Bearer {token()}"}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{url()}/api/states", headers=headers)
            r.raise_for_status()
            _cache["states"] = r.json()
            _cache["at"] = time.time()
            _last_error = ""
    except Exception as e:
        # stale cache beats an error page in the GUI, but record why
        _last_error = f"{e.__class__.__name__}: {e}"[:200]
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
