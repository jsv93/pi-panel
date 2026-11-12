# Study firmware candidate

This target uses the architectural linen Study layout at 720 × 1280 on the Waveshare engineering-sample ESP32-P4 with 32 MB flash. The screen assets come from the repository's kiosk HTML. Use a private build directory outside the checkout. The generated assets describe the room, and the firmware and YAML contain per-device credentials.

## Build

Use Python 3.11 with ESPHome 2026.6.5, NumPy, Pillow and Playwright with Microsoft Edge. From the repository root, run:

    python esphome/study/render.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/control_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/firmware.py PRIVATE_BUILD
    python esphome/p4_runtime/prepare.py PRIVATE_BUILD config-export.json --id DEVICE_ID --mac DEVICE_MAC --server SERVER_URL
    python -m esphome compile PRIVATE_BUILD/study-live.yaml

The export contains a top-level `config` object. The renderer takes a JSON array of HA state objects. Rendering uses an isolated browser with fixture sockets. Keep private firmware, state exports and provisioning files out of Git.

## Device and server

Each P4 needs its own fleet identity and ESPHome encryption key. Run `python esphome/p4_runtime/enroll.py PRIVATE_BUILD/fleet-identity.json --ip DEVICE_IP` to register it with the server. Use an authenticated HTTPS origin for enrollment when available. The existing HTTP deployment requires a trusted provisioning network. Claim the new P4 in the dashboard and import the Study configuration used for rendering. Home Assistant needs a native ESPHome connection with the generated encryption key and permission to perform HA actions.

The candidate downloads authenticated, signed configurations, keeps the last verified room profile in NVS and subscribes directly to HA light states. It can apply changes to Soft, Bright and preset participation. A configuration change that requires new artwork needs a new render. The worker starts after Ethernet connects. Touch navigation starts locally.

The normal ESPHome upload writes only the application images. This target also needs its matching motion bank and acceleration table. The fixed layout has two 3 MiB application slots, a motion partition starting at 0x610000 and NVS at 0x1f90000. The generated `live_runtime/motion_tail.h` gives the byte offset of `live-motion-tail.bin` within the motion partition. Verify the identity, partition table, space and image digests before installing. Preserve the previous working image.

## Coverage

Live bindings cover native HA light details, individual and group power, current climate readings and thermostat controls. Scene highlights follow confirmed HA levels with the kiosk's two-point tolerance. The initial Study speaker supports play, pause, previous, next, shuffle and repeat over the direct HA connection. Soft and Bright levels and participating lights use per-device server writes. A stopped server leaves the last signed profile active. Failed edits are shown on the panel and are discarded. The Display slider commits on release and overrides adaptive brightness for ten minutes. Standby uses the configured idle and blank intervals, HA time and ambient light. A wake touch is consumed before the underlying controls receive input.

The current firmware still includes captured widgets. Advanced light overlays, live media metadata and artwork, volume, seeking, library, queue and speaker selection, appearance and network settings, live diagnostics, and the production doorbell path require further implementation and verification.

## Hardware test

`tests/p4_study_touch.py PRIVATE_BUILD` generates a bench-only firmware configuration. The fixture light and thermostat clients exercise the regular touchscreen handlers without forwarding actions to the house. The default fleet destination is an unreachable loopback endpoint and uses the existing signed cache. The optional `--fixture-identity` selects a separate disposable server, credentials and NVS namespace for authenticated write and subsequent outage tests. Never deploy this image as the panel firmware. Restore and verify the paired image after testing.

`tests/p4_study_inventory.py` compares visible kiosk touch targets with the native hit regions. `tests/p4_study_numbers.py` measures RGB565 readout differences against Chromium. A matching touch rectangle alone only establishes reachability.

Pass `--capture` to the touch replay generator to export the actual 720 × 1280 framebuffer when each page settles. Save the USB log locally. Run `python tests/p4_study_capture.py PRIVATE_BUILD usb.log PRIVATE_FRAMES` to reconstruct every pixel and check the board's CRC for each view. The captures contain room information.
