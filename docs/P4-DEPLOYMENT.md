# Automatic P4 deployment

Supported target: Waveshare ESP32-P4 Wi-Fi 6 board with 32 MB flash, the 5-inch
720 × 1280 DSI display, and a FAT microSD card. Architectural and all six of its
palettes are supported. The current layout accepts 1–12 Home Assistant lights.
DALI is deliberately excluded until its hardware acceptance is available.

## First installation

A board needs a one-time USB installation of the matching bootloader, partition
table and application, plus its initial hash-named artwork in `pi-panel` on the
card. The bootloader must enable ESP-IDF OTA rollback. Preserve existing card
contents; the firmware never formats the card. Keep a copy of the previous
application and its artwork before migrating a board with an older bootloader.

Pair the board with Panel Server using its own device token and signing key,
and add its encrypted ESPHome connection to Home Assistant with HA actions
enabled. Keep private keys, configuration exports, artwork and firmware out of
GitHub. The public repository contains source and synthetic tests only.

Open that panel's **Diagnostics → P4 updates**. Enter its existing ESPHome
encryption key and enable automatic updates. The server reads the connected
device's name and verifies its MAC so the HA identity survives future builds.
This requires the existing server administrator session and configuration
ownership. It does not create SSH or shell access.

## Normal configuration changes

Use the existing Panel Server configuration pages. Changes needing different
artwork queue a private background build automatically. Palette, diagnostics,
library view, mini artwork and light preset values use the existing small signed
configuration protocol without compiling again. Diagnostics shows build and
installation progress and provides Retry for a failed build.

The first build downloads the pinned compiler toolchain. Later builds reuse
that toolchain. One low-priority worker runs at a time, with two compilation
jobs, outside the HTTP process. Build data stays in the add-on's persistent
`/data/p4` directory. The server keeps two installed releases for rollback and
two pending offers, and removes disposable capture/compiler output.

The panel stages immutable artwork and the application while idle. It verifies
every size and SHA-256, then writes only the inactive OTA application slot. A
device-specific signed manifest binds the hardware, MAC, generation and all
hashes. Artifact transfers are AES-256-CTR encrypted with separate keys per
device/generation/hash; the signed plaintext hash authenticates the result.
This protects private firmware contents on existing LAN HTTP deployments.
HTTPS also validates the server certificate when configured. Downloads support
byte-range resumption and pause when the panel is in use.

Before activation the panel checks that the offer is still current. It confirms
the new boot only after the display, touch, scanout and all required local
artwork are ready. This check does not depend on HA or Panel Server availability.
A failed health check rolls back. Failed generations are not retried in a loop;
Retry creates a new generation. Card cleanup only removes hashes recorded as
owned by this updater, while retaining the current and preceding healthy banks.
Unrelated card files and the legacy shared flash artwork partition are untouched.

## Offline operation

After provisioning, pages, palettes, animation artwork, Wi-Fi settings and the
last verified room configuration are local. Lights, climate, media, speaker
selection/transfer and library browsing communicate directly through HA's
encrypted ESPHome connection. They continue with Panel Server unavailable;
Home Assistant and the controlled devices still need to be reachable.

Panel Server is needed for new room/artwork deployments, central fleet graphs
and remote Identify/actions, server-owned configuration edits, and conversion
of provider logos that have not reached the bounded local cache. Doorbell
behavior depends on the configured camera path: direct MJPEG uses HA, while a
server-transcoded stream requires the server. The current acceptance uses the
Study Echo MJPEG source. A missing server must not prevent local boot.

The P4's RGB565 display and intermediate JPEG motion frames are not
pixel-identical to a Chromium compositor. Compare actual presented frames and
full-resolution captures, not the panel's nominal 55 Hz refresh rate.
