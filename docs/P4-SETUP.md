# First P4 installation

Use **Add panel → Waveshare P4 → Setup command → Install over USB** in Panel
Server. There are no installer files or identity reports to download and import.
Existing Pi setup and existing P4 update controls are unchanged.

Supported hardware is the Waveshare ESP32-P4 WiFi6 board with 32 MB flash,
engineering-sample silicon (USB validated on revision 1.3), and the Waveshare
5-inch 720 × 1280 DSI display. Other silicon generations and displays need their
own validated firmware. Use desktop Chrome or Edge on the computer connected
to the P4's USB data port.

1. Sign in to Panel Server. Its configured LAN URL must be reachable from the P4.
2. Click **Add panel**, choose **Waveshare P4**, and name the room. Choose a
   template, configure the room's Home Assistant lights, and save. This creates
   a new room without changing existing panels.
3. Open **Setup command → Install over USB**. HTTPS/localhost dashboards connect
   directly. HTTP dashboards and restricted HA ingress open the project's secure
   USB window automatically; click **Connect and install** there. Select the P4
   in the browser's USB device picker. An existing Pi Panel installation is
   detected and protected before any flash write.
4. The server binds this new room to the board and builds its firmware. Keep the
   setup window open. No second device selection or manual firmware download is
   needed. Installation replaces a new board's factory/demo firmware. Each
   written region is read back and checked against SHA-256 before restarting.
5. Insert a FAT32 microSD card and connect Ethernet. The P4 automatically loads
   its matching artwork onto the card. Follow progress in Panel Server; the
   screen may remain dark until artwork is ready. Interrupted downloads retry.
   No card is auto-formatted and unrelated files are retained.
6. Expand **Connect Home Assistant** for the address and encryption key. Add the
   ESPHome integration in HA and enable **Allow the device to perform Home
   Assistant actions**. Wi-Fi can then be configured using the P4's local controls.

Reopen the room's **Setup command** to resume preparation or view artwork progress.
Keep power and USB connected during writing. If writing is interrupted, retry
while the board is still identified as uninstalled. If it reports an existing
installation, restart it and check server progress instead of erasing it. A
damaged partition-table commit needs deliberate recovery; there is no automatic
bypass of the existing-install protection.

## Privacy and recovery

The secure window is a small static site hosted at
<https://jsv93.github.io/pi-panel/usb/>. It needs internet access to load, but
firmware passes directly between the two browser windows. The hosting service
does not receive firmware, household configuration, HA keys or administrator
credentials. Source-window, origin and random session identifiers bind messages
to the dashboard that opened it. The page displays that dashboard's origin.
Only authenticated configuration owners can prepare firmware or view HA keys;
these actions are audited. USB sessions expire after two hours, and packages
expire after 24 hours. Expiry is not credential revocation.

Only an allowlist of public browser files is published by `tools/build_usb_site.py`;
the website contains no server data or firmware. HTTPS dashboards can use the
same bundled USB code directly without contacting the public site.

New device credentials are created before the first connection. Artwork uses
the existing device-specific encrypted transport and SHA-256 hashes compiled
into firmware. Only an initial app0 boot with no OTA selection can fetch artwork
before local display health is established. Pending/valid OTA slots cannot use
that path. Installation is confirmed only after the display and artwork are healthy.

After setup, cached layout, artwork, settings and controls continue to work with
Panel Server offline. HA-backed controls still require HA. The existing P4 DALI
limitation is unchanged. Later firmware updates retain inactive-slot installation
and health-based rollback.

## Validation status

The working Study P4 passed read-only USB identification and 460800-baud checks
on Windows. The user confirmed browser identification and existing-install
detection. Its flash and artwork have not been replaced for this wizard.

Tests cover authorization, private packaging, device binding, installed/wrong-board
rejection, bounded writes, readback failure, the actual pinned serial library's
write API, dashboard CSP, direct HTTPS, the real cross-window HTTP/HA-ingress
handoff and the existing Pi setup default. Physical flash is simulated in those
browser tests. Initial-install firmware has compiled locally and is included in
the complete-room CI build. **A physical clean install and first-time automatic
artwork download still require a spare P4 and have not been hardware validated.**
