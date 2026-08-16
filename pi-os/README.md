# Pi kiosk boot (Raspberry Pi OS Lite + cage)

Boots straight to the panel UI with no desktop environment installed at all.

**The config server does this for you.** Provisioning a panel from the GUI runs
a bootstrap script that installs everything here as part of the same pass. These
files are the standalone equivalent, for a Pi being set up without the server or
one that already has the agent.

## Why this instead of a desktop session

Raspberry Pi OS Desktop kiosk (autologin → labwc/wayfire → an autostart entry)
has several moving parts that all have to agree: autologin timing, the
compositor's own session lifecycle, which of three autostart mechanisms that
image actually honours, screen blanking settings living in three places, and a
session manager that assumes a human might be using it.

Every one of those failed at least once during bring-up. The worst was subtle:
a session restart left the old Chromium alive but detached from a dead
compositor, and because Chromium is a singleton per profile, every relaunch
handed its URL to that invisible process and exited. The panel showed white and
nothing in the logs said why.

`cage` removes the category. It is a Wayland compositor whose only job is "run
one app fullscreen, exit when it exits". On Pi OS Lite there is no session to
restart, no compositor to drop out, and nothing else contesting the display.
systemd supervises it directly.

## Getting a panel onto the wall

Three routes, in order of least work:

1. **SD-card drop-in.** The GUI generates a `firstrun.sh` for that specific
   panel; copy it onto the boot partition after flashing. On first boot the
   panel sets its hostname, installs the server's key, provisions itself and
   reboots into the UI. Nothing to discover, no SSH, no IP.
2. **Install over SSH** from the GUI, for a panel already booted and reachable.
   **Find panels on the network** locates it without going to the router.
3. **The command by hand**, for when something has gone wrong and you want to
   watch it happen.

All three run the same bootstrap and consume the same one-time token, so there
is one provisioning path however it is triggered.

The drop-in needs **Ethernet**: `firstrun.sh` runs under
`systemd.unit=kernel-command-line.target`, before networking exists, which is
why it defers the actual provisioning to a oneshot unit that runs after the
reboot rather than fetching anything itself. Wifi would need to be configured
by Imager separately.

## Prerequisites

- Raspberry Pi OS **Lite** (64-bit) — flash this, not the Desktop image
- `agent/panel-agent.py` and `panel-ui/backlight.py` installed (the server's
  bootstrap script does this; otherwise see `server/README.md`)

## Install

    sudo pi-os/setup.sh

That installs `cage` and `chromium`, adds the DSI overlay to `config.txt` if
missing, creates the `panel` system user with a writable home for Chromium's
profile, and installs and enables the unit.

The service runs on `tty2`, not `tty1`, to avoid fighting the default
`getty@tty1` — nothing Raspberry Pi OS ships needs disabling.

## Reliability: protect the SD card

CM5 Lite has no eMMC, and SD corruption from a power cut is the most common
field failure on a 24/7 wall panel. Enable the overlay filesystem once a panel
is otherwise finished:

    sudo raspi-config   # Advanced Options -> Overlay File System -> enable both

This is what the purpose-built kiosk distros are really selling, available on
stock Raspberry Pi OS without giving up the kernel and firmware support that
actually gets tested against this hardware.

**It also makes the root filesystem read-only**, so re-provisioning a panel
from the server does nothing until you turn it back off. Disable it before
updating a panel, re-enable afterwards.

## Verify

    systemctl status cage-kiosk
    journalctl -u cage-kiosk -f

Chromium should be fullscreen within a few seconds of `cage-kiosk` starting.

## Troubleshooting

- **Blank screen, nothing in the journal**: point the URL at `chrome://gpu`
  temporarily and confirm hardware acceleration is active. Without
  `--ozone-platform=wayland` Chromium can silently fall back to software
  rendering, which does not fail visibly — it just looks like the compositor
  change achieved nothing. See `docs/PI-KIOSK-FINDINGS.md`.
- **cage fails to acquire DRM / seat**: `PAMName=login` in the unit is what
  makes systemd-logind grant the seat, so confirm `systemd-logind` is running.
  If it genuinely is not available, `seatd` is the fallback — do not run both.
- **Works over SSH but not on boot**: an interactive SSH session already holds
  a logind session, which changes seat arbitration. Always test with a cold
  reboot rather than `systemctl restart` while logged in.
- **No signal from the display at all**: the DSI overlay is missing from
  `config.txt` and a reboot is needed. `setup.sh` adds it, but a fresh Lite
  image will not have it.
- **`panel-kiosk-launch: not found`**: re-run `setup.sh` — the script needs its
  executable bit.
