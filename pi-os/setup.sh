#!/bin/sh
# Kiosk provisioning for Raspberry Pi OS Lite (64-bit). Idempotent.
# Run as root: sudo pi-os/setup.sh
#
# The config server's bootstrap script does all of this automatically as part
# of provisioning a panel. This is the standalone path, for a Pi that already
# has the agent installed or one being set up without the server.
#
# See pi-os/README.md for the overlay filesystem step, which is deliberately
# not automated -- it is an interactive raspi-config menu, and you do not want
# a read-only root while you are still setting the panel up.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

apt-get update
apt-get install -y cage curl
apt-get install -y chromium || apt-get install -y chromium-browser

# The panel is the same Waveshare 5-DSI-TOUCH-A used on the ESP board. Stock
# Raspberry Pi OS auto-detects only the official Touch Display, so without this
# the panel gets no signal at all -- not a blank desktop, nothing.
CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
if [ -f "$CONFIG" ] && ! grep -q 'vc4-kms-dsi-waveshare-panel' "$CONFIG"; then
  cp "$CONFIG" "$CONFIG.panel-backup"
  grep -q '^dtoverlay=vc4-kms-v3d' "$CONFIG" || printf '\ndtoverlay=vc4-kms-v3d\n' >> "$CONFIG"
  printf 'dtoverlay=vc4-kms-dsi-waveshare-panel-v2,5_0_inch_a\n' >> "$CONFIG"
  echo "Added the DSI overlay to $CONFIG -- a reboot is required."
fi

id -u panel >/dev/null 2>&1 || useradd -r -G video,input,render -d /var/lib/panel-kiosk panel
install -d -o panel -g panel -m 0755 /var/lib/panel-kiosk

install -m 0755 "$SCRIPT_DIR/kiosk-launch.sh" /usr/local/bin/panel-kiosk-launch
install -m 0644 "$SCRIPT_DIR/cage-kiosk.service" /etc/systemd/system/cage-kiosk.service

systemctl daemon-reload
systemctl enable cage-kiosk

echo
echo "Provisioned. Two things left, deliberately not automated:"
echo "  1. sudo raspi-config -> Advanced Options -> Overlay File System"
echo "     (enable once the panel is otherwise done being set up)"
echo "  2. Reboot to start the kiosk cold: sudo reboot"
