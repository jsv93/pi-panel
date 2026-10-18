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
import glob, json, os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

def find_device():
    """Resolved per request, not once at import.

    systemd starts this service before the DSI panel has necessarily
    registered its backlight, and /sys/class/backlight is empty until it does.
    Resolving once at import meant an early start left DEV as None for the
    lifetime of the service — the brightness control silently did nothing
    until someone restarted it.
    """
    c = sorted(glob.glob("/sys/class/backlight/*/brightness"))
    if not c:
        return None, 255
    dev = c[0]
    maxf = dev.replace("brightness", "max_brightness")
    try:
        mx = int(open(maxf).read().strip())
    except Exception:
        mx = 255
    return dev, (mx or 255)


def blank(dev, on):
    """Drive bl_power directly.

    Writing brightness 0 is not the same as off on this panel -- it still
    glows enough to be obvious in a dark room. bl_power uses the framebuffer
    blanking levels: 0 is FB_BLANK_UNBLANK, 4 is FB_BLANK_POWERDOWN.
    """
    p = os.path.join(os.path.dirname(dev), "bl_power")
    try:
        if os.path.exists(p):
            with open(p, "w") as f:
                f.write("4" if on else "0")
    except Exception:
        pass


def unblank(dev):
    """Clear bl_power before writing brightness.

    While bl_power is non-zero the panel is blanked and a brightness write
    lands in sysfs but changes nothing on screen. That is why setting the
    slider appeared not to take until it had been moved a few times: something
    else (the compositor's idle handling, or systemd-backlight at boot) had
    blanked it, and only a write that happened to coincide with an unblank
    was visible.
    """
    p = os.path.join(os.path.dirname(dev), "bl_power")
    try:
        if os.path.exists(p) and open(p).read().strip() != "0":
            with open(p, "w") as f:
                f.write("0")
    except Exception:
        pass


class BrightnessRamp:
    """One interruptible hardware fade. New requests retarget from the actual
    level; zero cancels the fade and blanks immediately under the same lock.
    HTTP requests return immediately, so a pending fade cannot delay blanking.
    """
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.dev = None
        self.target = self.current = 0
        self.duration = 0
        self.error = None

    def request(self, dev, maximum, value, transition_ms=400):
        with self.lock:
            target = round(value / 255 * maximum)
            if value == 0:
                self.duration = 0
                self.dev, self.target, self.current = dev, 0, 0
                with open(dev, 'w') as f:
                    f.write('0')
                blank(dev, True)
                self.error = None
                return
            current = int(open(dev).read().strip())
            power = os.path.join(os.path.dirname(dev), 'bl_power')
            is_blanked = os.path.exists(power) and open(power).read().strip() != '0'
            if (dev == self.dev and target == self.target and not self.error
                    and not is_blanked and current == self.current):
                # Repeated targets must not restart an in-progress fade, but
                # an externally blanked display still needs to wake.
                return
            if is_blanked:
                current = 0
                with open(dev, 'w') as f:
                    f.write('0')
            unblank(dev)
            self.dev, self.target, self.current = dev, target, current
            self.start, self.started = current, self.clock()
            self.duration = transition_ms / 1000
            self.error = None
            if not self.duration:
                with open(dev, 'w') as f:
                    f.write(str(target))
                self.current = target

    def tick(self):
        with self.lock:
            if not self.duration:
                return
            progress = min(1, max(0, (self.clock() - self.started) / self.duration))
            level = round(self.start + (self.target - self.start) * progress)
            try:
                if level != self.current:
                    with open(self.dev, 'w') as f:
                        f.write(str(level))
                    self.current = level
                if progress >= 1:
                    self.duration = 0
            except OSError:
                # A disconnected screen can be retried by the next request.
                self.duration = 0
                self.error = 'Backlight write failed'

    def run(self):
        while True:
            self.tick()
            time.sleep(.02)  # 50 Hz; write only changed hardware steps.


RAMP = BrightnessRamp()


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
        dev, mx = find_device()
        if dev:
            try:
                v = int(q.get("v", ["255"])[0])
                v = max(0, min(255, v))
                transition = max(0, min(60000, int(q.get('transition_ms', ['400'])[0])))
                scaled = round(v / 255 * mx)
                RAMP.request(dev, mx, v, transition)
                ok, msg = True, ("off" if v == 0 else f"{scaled}/{mx}")
            except Exception as e:
                msg = str(e)
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "text/plain"); self._cors(); self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    _dev, _max = find_device()
    print(f"backlight device: {_dev or 'NONE (will re-check per request)'} (max {_max})")
    threading.Thread(target=RAMP.run, daemon=True, name='backlight-fade').start()
    HTTPServer(("127.0.0.1", 8081), H).serve_forever()
