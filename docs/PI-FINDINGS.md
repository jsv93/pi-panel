# Raspberry Pi panel — bring-up notes

Things that cost time on the Pi side. The bootstrap script does all of this
automatically; this is here so the knowledge survives a reflash, which is how
it was lost the first time.

## Display

The panel is the same Waveshare 5-DSI-TOUCH-A (HX8394) used on the ESP board.

Stock Raspberry Pi OS auto-detects only the **official** Raspberry Pi Touch
Display. A third-party DSI panel with no overlay gets no signal at all — not a
blank desktop, nothing. A fresh install therefore looks like dead hardware.

In `/boot/firmware/config.txt`:

    dtoverlay=vc4-kms-v3d
    dtoverlay=vc4-kms-dsi-waveshare-panel-v2,5_0_inch_a

Append `,dsi0` to the second line if the ribbon is on the DSI0 connector.
Requires a reboot.

Two consequences worth knowing:

- `/sys/class/backlight/` is empty until the overlay works, so `backlight.py`
  has no device and the brightness control does nothing. That is a symptom of
  the display problem, not a separate fault.
- On Pi 5, panel revisions Rev2.1 and earlier can trip the Pi 5's power
  detection, which misreads the panel's capacitors as a short and refuses to
  power it. No amount of `config.txt` fixes that one — check the board
  revision before assuming it is software.

## systemd

`systemctl enable --now` does **not** restart a unit that is already running.
Rewriting `panel-agent.service` and calling `enable --now` leaves an old agent
running with its old `PANEL_SERVER`, so the new unit is silently ignored and
the panel appears never to connect. Always `restart` after `daemon-reload`.

## Names

`.local` names do not resolve reliably here — not from the Pi to the server,
and not from inside the server's Docker container to Home Assistant. Use IP
addresses in `PANEL_SERVER`, `HA_URL`, and the panel's configured HA address.

An agent pointed at an unresolvable host fails with
`Cannot connect to host <name> [Domain name not found]` in
`journalctl -u panel-agent`, which is the fastest way to spot it.

## Identity

A panel's identity is the server-issued id in `/opt/panel/panel-id`, not the
hostname. Renaming the Pi is safe. If that file is missing the agent falls
back to the hostname, which is the pre-provisioning behaviour and will create
a second, unclaimed record if the panel was provisioned from the GUI.
