#!/usr/bin/env python3
"""
Tiny localhost helper so the panel UI can set screen brightness.

The Pi's DSI overlay exposes the panel backlight in sysfs, so we just
write to it. Run this as a service; the UI calls GET /backlight?v=0-255.

  sudo cp backlight.py /usr/local/bin/panel-backlight
  sudo chmod +x /usr/local/bin/panel-backlight

Then /etc/systemd/system/panel-backlight.service:

  [Unit]
  Description=Panel backlight helper
  [Service]
  ExecStart=/usr/local/bin/panel-backlight
  Restart=always
  [Install]
  WantedBy=multi-user.target

  sudo systemctl enable --now panel-backlight
"""
import glob, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

CANDIDATES = sorted(glob.glob("/sys/class/backlight/*/brightness"))
DEV = CANDIDATES[0] if CANDIDATES else None
MAXF = DEV.replace("brightness", "max_brightness") if DEV else None
MAX = int(open(MAXF).read().strip()) if MAXF and os.path.exists(MAXF) else 255


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q0 = parse_qs(u.query)
        if u.path == "/state":
            # the panel UI reports its HA connection here; the sync agent reads it
            try:
                with open("/opt/panel/state.json", "w") as f:
                    json.dump({"ha_connected": q0.get("ha", ["0"])[0] == "1"}, f)
            except Exception:
                pass
            self.send_response(204); self._cors(); self.end_headers(); return
        if u.path != "/backlight":
            self.send_response(404); self._cors(); self.end_headers(); return
        q = parse_qs(u.query)
        ok, msg = False, "no backlight device found"
        if DEV:
            try:
                v = int(q.get("v", ["255"])[0])
                v = max(0, min(255, v))
                scaled = round(v / 255 * MAX)
                with open(DEV, "w") as f:
                    f.write(str(scaled))
                ok, msg = True, f"{scaled}/{MAX}"
            except Exception as e:
                msg = str(e)
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "text/plain"); self._cors(); self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"backlight device: {DEV or 'NONE'} (max {MAX})")
    HTTPServer(("127.0.0.1", 8081), H).serve_forever()
