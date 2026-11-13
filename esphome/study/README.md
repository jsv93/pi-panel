# Study firmware candidate

This target uses the architectural linen Study layout at 720 × 1280 on the Waveshare engineering-sample ESP32-P4 with 32 MB flash. The screen assets come from the repository's kiosk HTML. Use a private build directory outside the checkout. The generated assets describe the room, and the firmware and YAML contain per-device credentials.

## Build

Use Python 3.11 with ESPHome 2026.6.5, NumPy, Pillow and Playwright with Microsoft Edge. From the repository root, run:

    python esphome/study/render.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/control_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/media_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/text_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/firmware.py PRIVATE_BUILD
    python esphome/p4_runtime/prepare.py PRIVATE_BUILD config-export.json --id DEVICE_ID --mac DEVICE_MAC --server SERVER_URL
    python -m esphome compile PRIVATE_BUILD/study-live.yaml

The export contains a top-level `config` object. The renderer takes a JSON array of HA state objects. Rendering uses an isolated browser with fixture sockets. Keep private firmware, state exports and provisioning files out of Git.

## Device and server

Each P4 needs its own fleet identity and ESPHome encryption key. Run `python esphome/p4_runtime/enroll.py PRIVATE_BUILD/fleet-identity.json --ip DEVICE_IP` to register it with the server. Use an authenticated HTTPS origin for enrollment when available. The existing HTTP deployment requires a trusted provisioning network. Claim the new P4 in the dashboard and import the Study configuration used for rendering. Home Assistant needs a native ESPHome connection with the generated encryption key and permission to perform HA actions.

The candidate downloads authenticated, signed configurations, keeps the last verified room profile in NVS and subscribes directly to HA light states. It can apply changes to Soft, Bright and preset participation. A configuration change that requires new artwork needs a new render. The worker starts after Ethernet connects. Touch navigation starts locally.

The normal ESPHome upload writes only the application images. This target also needs its matching motion bank, acceleration table and volume artwork. The fixed layout has two 3 MiB application slots, a motion partition starting at 0x610000 and NVS at 0x1f90000. The generated `live_runtime/motion_tail.h` gives the offsets of `live-motion-tail.bin` and `volume-art.bin` relative to the start of the motion partition. Provision the volume bank at `0x610000 + volume_offset` and verify its SHA-256 against `volume_sha`. The previous paired build does not use those sectors. Verify the device, partition layout and digests before installing. Preserve the previous working image.

The Wi-Fi candidate uses the onboard ESP32-C6 on the Waveshare ESP32-P4-WIFI6-POE-ETH. Pass `--hosted-wifi` to `prepare.py` after regenerating the motion bank and text art. This build also requires `text-art.bin` at `0x610000 + text_offset`. Its compact motion index moves the acceleration and volume offsets. Back up the entire current motion partition with its application before swapping builds. Restore both together when reverting. Preserve the NVS partition. The firmware checks the external text asset digest before drawing the panel.

## Coverage

Live bindings cover native HA light details, individual and group power, current climate readings and thermostat controls. Scene highlights follow confirmed HA levels with the kiosk's two-point tolerance. The initial Study speaker supports play, pause, previous, next, shuffle and repeat over the direct HA connection. Soft and Bright levels and participating lights use per-device server writes. A stopped server leaves the last signed profile active. Failed edits are shown on the panel and are discarded. The Display slider commits on release and overrides adaptive brightness for ten minutes. Standby uses the configured idle and blank intervals, HA time and ambient light. A wake touch is consumed before the underlying controls receive input.

The light More sheets expose the captured effects, warmth, colour and preset membership for each configured light. The volume popup and transport controls operate on the configured speaker over its Home Assistant connection.

An admin test ring uses the paired device’s long poll. Panel Server retrieves the configured Home Assistant MJPEG stream and transcodes frames for the P4. If the server is unreachable, the panel can request that camera’s MJPEG stream directly with a camera-specific playback credential received through its encrypted ESPHome subscription. A direct ring then requires the configured HA trigger or the encrypted `ring_live_camera` action. A source that provides only WebRTC or HLS needs a separate video path.

The relay preserves the camera aspect ratio. The P4 fits each frame into the video rectangle measured from the kiosk HTML and draws the status and duration from the same layout. If a server stream ends during a ring, the same overlay can continue from Home Assistant.

The Home player and Music screen use the configured speaker’s HA title, artist, position and duration. The seek action is available when the speaker reports support. The queue shows the current track and reported playlist or album. The panel can decode baseline JPEG cover art from the configured HA host, including a Music Assistant image endpoint on that host. The Home artwork preference persists on the device.

The Music screen lists the configured speakers and switches its transport, volume, timeline and artwork to the selection. Queue transfer uses the Music Assistant action and waits for Home Assistant to confirm. The destination needs an available Music Assistant player with a different queue. The library browses Home Assistant directly, pages through large folders, and offers tile and list views. Selecting a playable track sends it to the selected speaker. The library view preference persists locally. Visible items can load baseline JPEG thumbnails over HTTPS or from the HA host. PNG, signed relative thumbnail paths and unsupported image sizes retain the kiosk fallback icon.

The room menu date, Home Assistant connection, network, backlight, display refresh and uptime readings come from the P4. Enabling diagnostics places the HA connection and display refresh rate in the top corners. The preference persists across restarts. The scroll test measures completed presentations across six native list-rendering workloads and shows the results on the panel. Browser compositor workloads and native renderer workloads measure different operations.

The asset generator accepts all six Architectural palettes for individual builds. In-panel palette switching and the Default and Ambient layouts remain open. The Network screen in the hosted Wi-Fi candidate scans the 2.4 GHz band and accepts an SSID selection and a passphrase on its touch keyboard. The worker waits for authentication and a DHCP lease before saving a new network. The working room uses Architectural and Linen over Ethernet.

To build the shared palette artwork, render each Architectural palette into a subdirectory named after its palette, then run `python esphome/study/palette_art.py PALETTE_DIRECTORY PRIVATE_BUILD/study-palettes.bin`. The encoder reopens the packed sections and checks every pixel of every resting screen against the original RGB565 render. The pack covers resting screens. Interactive controls and motion still need runtime palette support.

## Hardware test

`tests/p4_study_touch.py PRIVATE_BUILD` generates a bench-only firmware configuration. The fixture light and thermostat clients exercise the regular touchscreen handlers without forwarding actions to the house. The default fleet destination is an unreachable loopback endpoint and uses the existing signed cache. The optional `--fixture-identity` selects a separate disposable server, credentials and NVS namespace for authenticated write and subsequent outage tests. Never deploy this image as the panel firmware. Restore and verify the paired image after testing.

`tests/p4_study_inventory.py` compares visible kiosk touch targets with the native hit regions. `tests/p4_study_numbers.py` measures RGB565 readout differences against Chromium. A matching touch rectangle alone only establishes reachability.

Pass `--capture` to the touch replay generator to export the actual 720 × 1280 framebuffer when each page settles. Save the USB log locally. Run `python tests/p4_study_capture.py PRIVATE_BUILD usb.log PRIVATE_FRAMES` to reconstruct every pixel and check the board's CRC for each view. The captures contain room information.

For a comparison with real Home Assistant readings, first generate the bench configuration with a separate fixture identity. Run `python tests/p4_study_live_views.py PRIVATE_BUILD` and compile the resulting `study-views.yaml`. This replay uses the panel's real HA state subscriptions. It navigates through the room, light sheets, Music popups and doorbell, then returns Home. Capture the UART at 1,500,000 baud through `LIVE_VIEWS_DONE`. Run `python tests/p4_study_capture.py --live PRIVATE_BUILD usb.log PRIVATE_FRAMES` to verify the captured frames. Use a separate run after stopping the test server and rebooting the panel. Restore the enrolled application when the comparison finishes.
