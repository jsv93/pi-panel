#!/bin/sh
# Launched by cage-kiosk.service. Waits for panel-agent's local HTTP server to
# accept connections -- systemd's After= only guarantees the process started,
# not that aiohttp has bound the port -- then hands off to cage, which runs
# chromium as its only window. If chromium exits, cage exits, and the unit's
# Restart=always brings the pair back.
set -eu

UI_URL="http://127.0.0.1:8088/panel.html"

CHROME=$(command -v chromium || command -v chromium-browser || true)
if [ -z "$CHROME" ]; then
  echo "no chromium on PATH" >&2
  exit 1
fi

i=0
until curl -sf -o /dev/null "$UI_URL"; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "panel-agent never came up after 30s, launching anyway" >&2
    break
  fi
  sleep 0.5
done

# After a power cut chromium offers to restore pages, which parks a dialog on a
# panel with no keyboard. Cleared on every start, not just the first.
PREF="$HOME/chromium/Default/Preferences"
if [ -f "$PREF" ]; then
  sed -i 's/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREF" || true
fi

# Flag notes, all of these earned on hardware:
#   --ozone-platform=wayland  chromium does not necessarily render natively via
#     Wayland/DRM without it, and software rendering would not fail visibly --
#     it would just look like "the lighter compositor made no difference".
#   NetworkServiceInProcess   the out-of-process network service was crashing
#     about a minute in on this panel, leaving a blank page with the browser
#     still running. /dev/shm and memory were both ruled out.
#   --disable-background-networking and friends remove the push-messaging
#     client that was retrying dead Google endpoints through that service.
#   Both features go in ONE --enable-features: a second occurrence replaces the
#     first rather than adding to it.
exec cage -- "$CHROME" \
  --kiosk "$UI_URL" \
  --ozone-platform=wayland \
  --enable-features=UseOzonePlatform,NetworkServiceInProcess \
  --disable-features=TranslateUI \
  --user-data-dir="$HOME/chromium" \
  --password-store=basic \
  --disable-background-networking \
  --disable-sync \
  --disable-component-update \
  --disable-domain-reliability \
  --no-default-browser-check \
  --no-service-autorun \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000 \
  --no-first-run
