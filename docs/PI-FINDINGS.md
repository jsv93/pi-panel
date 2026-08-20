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

The size parameter is per panel and is set from the panel's Display
configuration. **An unrecognised parameter is silently ignored**, and the panel
then initialises with the wrong timings: backlight on, touch responding, and a
picture of white lines fading in and out as the input changes. That reads as
broken hardware and is not — it is a bad config line.

To see what the installed overlay accepts, rather than guessing from the model
name — a Waveshare wiki page for a neighbouring product will happily give you
a parameter for the wrong panel:

    dtoverlay -h vc4-kms-dsi-waveshare-panel-v2

The screen picker's list is taken from that output. Sizes run 3.4" to 12.3",
several have A/B/C variants at different resolutions, and the larger ones have
2-lane and 4-lane forms — so the model name alone does not determine the
parameter.

**Two DSI overlay lines is worse than none.** Provisioning replaces any
existing one, but a panel set up before that behaviour existed, or edited by
hand, can end up with two drivers contending for one DSI link — white lines
fading in and out as the input changes, with backlight and touch both working.
Check with `grep dtoverlay /boot/firmware/config.txt`.

Two consequences worth knowing:

- `/sys/class/backlight/` is empty until the overlay works, so `backlight.py`
  has no device and the brightness control does nothing. That is a symptom of
  the display problem, not a separate fault.
- On Pi 5, panel revisions Rev2.1 and earlier can trip the Pi 5's power
  detection, which misreads the panel's capacitors as a short and refuses to
  power it. No amount of `config.txt` fixes that one — check the board
  revision before assuming it is software.

## Kiosk

The panel runs **Raspberry Pi OS Lite** with `cage`, not a desktop session.
See `pi-os/README.md`. What follows is why, kept because the failures are
instructive and none of them were obvious from the symptom.

The desktop-session approach (autologin → labwc/wayfire → autostart entry) was
abandoned after every one of these bit:

- **Which autostart mechanism fires varies by image.** XDG autostart worked on
  this one; adding labwc's as a "fix" produced two launchers, which fought over
  the browser and restarted the panel every five seconds. Seeding labwc's file
  from `/etc/xdg` also started every desktop component twice — two task bars.
- **Chromium is a singleton per profile.** After a session restart the previous
  Chromium was still alive but detached from a dead compositor, so every
  relaunch handed it the URL and exited. White screen, nothing in any log,
  indistinguishable from the page failing to load.
- **`pkill -f /usr/bin/chromium` matches nothing.** That path is a wrapper
  script; the process holding the profile is `/usr/lib/chromium/chromium`.
- **The compositor can vanish underneath it** — `Fatal Wayland communication
  error: Broken pipe` — killing the browser with no supervisor to restart it.

`cage` removes the category rather than patching it: one app, no session, no
autologin, systemd supervising directly.

Two things carried over into the cage launcher because they were real and are
not compositor-specific:

- The out-of-process network service crashed about a minute into every run,
  leaving a blank page with the browser still up. `/dev/shm` (1.9G, 1% used),
  memory and profile ownership were all ruled out. Runs in-process now.
- Chromium's push-messaging client retries dead Google endpoints
  (`DEPRECATED_ENDPOINT`) through that same service. Background networking is
  disabled outright.

The cursor is dealt with by a udev rule, not by CSS and not by `unclutter` —
see "The cursor that would not go away" below.

## Getting a shell on a panel

Provisioning tells you to paste the *server's* public key into Raspberry Pi
Imager. If that is the only authentication configured, the panel accepts
public-key auth and nothing else — and the matching private key is on the
server, not on your machine. An SSH client then reports something like "no
supported authentication methods (server sent: publickey)", which reads as a
client problem and is not.

**Paste two keys, one per line**: the server's, and your own. Imager's
authorized_keys box takes any number and sshd will accept any of them, so
provisioning keeps working and you can still get a shell.

    ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519

Adding a password instead also works — sshd allows password and public-key
auth simultaneously, so it does not displace the server's key — but whether
Imager still writes the key when password authentication is selected depends
on its UI, and two keys avoids the question entirely.

If a panel is already in that state, the server's private key can be read from
the add-on's data directory using Home Assistant's Terminal & SSH add-on:

    cat /mnt/data/supervisor/addons/data/*panel_server/ssh/id_ed25519

Windows has an OpenSSH client built in and reads that file as-is; PuTTY needs
it converted with PuTTYgen first.

## systemd

`systemctl enable --now` does **not** restart a unit that is already running.
Rewriting `panel-agent.service` and calling `enable --now` leaves an old agent
running with its old `PANEL_SERVER`, so the new unit is silently ignored and
the panel appears never to connect. Always `restart` after `daemon-reload`.

## Names

The signature to watch for: `curl http://something.local:8099` works, but the
agent logs `Cannot connect to host something.local [Domain name not found]`
for the identical host.

That is a resolver difference, not a network fault. aiohttp uses the c-ares
`AsyncResolver` whenever `aiodns` is importable, and Debian's
`python3-aiohttp` pulls `aiodns` in as a dependency. c-ares speaks plain DNS
and never consults NSS, so `nss-mdns` — the thing that resolves `.local` — is
bypassed entirely. `curl` goes through NSS and is unaffected.

Installing aiohttp with `pip` brings no `aiodns`, so the agent used to get
`ThreadedResolver` (which calls `getaddrinfo`, hence NSS, hence mDNS) purely
by accident. Moving the bootstrap to `apt` changed the resolver underneath it.

The agent now pins `ThreadedResolver` explicitly, so `.local` works again.
To check whether a given panel has the c-ares resolver:

    python3 -c "import aiohttp.resolver as r; print(r.DefaultResolver.__name__)"

Prefer IP addresses anyway. Inside the server's Docker container mDNS does not
work at all, so `HA_URL` in particular must be an IP.

## Identity

A panel's identity is the server-issued id in `/opt/panel/panel-id`, not the
hostname. Renaming the Pi is safe. If that file is missing the agent falls
back to the hostname, which is the pre-provisioning behaviour and will create
a second, unclaimed record if the panel was provisioned from the GUI.

## The cursor that would not go away

`libinput list-devices` on this panel:

    Goodix Capacitive TouchScreen   keyboard touch
    vc4-hdmi-0                      keyboard pointer
    vc4-hdmi-1                      keyboard pointer

The touchscreen is touch-only, correctly. The **HDMI ports** advertise pointer
capability — they are CEC / jack-detect nodes the kernel exposes as input
devices. They never emit motion, but wlroots sees a pointer and draws a cursor,
which then sits there permanently because nothing can move it.

Two things that look like fixes and are not:

- `cursor:none` in the page. Touch is not pointer input on Wayland, so a
  touch-only panel never produces a pointer-enter event, chromium is never
  asked to render a cursor, and the CSS never gets a chance to apply. This is
  also why it used to vanish on first touch under a desktop session and does
  not under cage.
- `XCURSOR_SIZE=1`. Tried, did nothing.

The fix is to stop libinput seeing those devices at all, via
`pi-os/99-panel-ignore-hdmi-input.rules`:

    SUBSYSTEM=="input", ATTRS{name}=="vc4-hdmi*", ENV{LIBINPUT_IGNORE_DEVICE}="1"

`libinput` itself is in `libinput-tools`, which Lite does not install.

## Re-provisioning an existing panel

Re-provisioning issues a **new** panel id, so the server's config for it starts
again at version 1. The config already on the Pi belongs to the old record and
is typically at a higher version.

The agent used to skip a sync when the server's version was `<=` the local one,
which meant a re-provisioned panel kept showing the previous room's lights and
speakers and ignored every subsequent push — while the GUI correctly showed
nothing assigned. Nothing logged an error; both halves believed they were right.

Two changes, either of which fixes it, kept together because they fail
independently:

- The bootstrap deletes `config.json` when the id on disk differs from the id
  being provisioned. `secrets.json` is kept: same hardware, same Home
  Assistant, and the token is not identity-specific.
- The agent compares versions with `!=` rather than `<=`. A lower version on
  the server does not mean the panel is ahead; it means the record was
  replaced.

## Updating a panel that is already installed

`panel.html`, the agent and the backlight helper are fetched **once**, during
provisioning. A panel does not pick up new ones on its own, so a server update
alone changes nothing on the wall.

Use **Reinstall** on the panel's page. It issues a fresh token against the
*existing* panel id, so the bootstrap leaves `config.json` alone and the panel
comes back as itself — same room, entities and version history — with the
current files. It reboots at the end.

Creating a new panel record instead would hand out a new id and abandon the
room's configuration, which is what the id-change branch in the bootstrap is
there to detect.

For a one-file change while iterating, copying it straight over is faster than
a reinstall:

    scp panel-ui/panel.html joel@<panel>:/tmp/
    ssh joel@<panel> "sudo mv /tmp/panel.html /opt/panel/current/panel.html \
      && sudo systemctl restart cage-kiosk"

## Bundle self-update

Panels keep their own `panel.html`, agent and backlight helper current. The
agent compares each file's sha256 against `/bundle/manifest` on every config
poll and pulls only what differs.

Hashes rather than a version number: nothing to remember to bump, and a file
edited by hand at either end is noticed.

What happens after each file lands:

- `panel.html` — the page is told to reload
- `backlight.py` — its service is restarted
- the agent — replaced, then it exits so systemd starts the new one

Replacing the agent with itself running is the risky one, so it is guarded at
three points. The download must match the manifest hash. A `.py` file must
compile, because a syntax error would restart-loop the agent forever. And the
previous binary is kept: the replacement writes a marker, and if it cannot
register within a minute it restores the old one and exits. A panel cannot be
stranded by a bad agent.

**This does not replace Reinstall.** It covers the three files fetched at
provisioning. Anything install-time — apt packages, cage and chromium, the
systemd units, the DSI overlay, the udev rule — still needs a reinstall.
