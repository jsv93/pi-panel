#!/bin/sh
# Add-on entrypoint. Turns /data/options.json into the environment the app
# already understands, so the same code runs here and standalone.
#
# Python rather than bashio or jq: this image is python:3.12-slim to match the
# standalone build, and adding a JSON parser to it just to read one file would
# be the only reason either exists.
set -e

OPTS=/data/options.json
if [ -f "$OPTS" ]; then
  eval "$(python3 - "$OPTS" <<'PY'
import json, shlex, sys
try:
    o = json.load(open(sys.argv[1]))
except Exception:
    o = {}
for key, env in (("admin_password", "ADMIN_PASSWORD"), ("panel_url", "PANEL_URL")):
    v = str(o.get(key) or "").strip()
    if v:
        print(f"export {env}={shlex.quote(v)}")
PY
)"
fi

# Nothing sets HA_URL or HA_TOKEN here. With homeassistant_api: true the
# Supervisor provides SUPERVISOR_TOKEN and proxies the core API, and ha.py
# falls back to that when neither is configured.

exec uvicorn app.main:app --host 0.0.0.0 --port 8099
