# Study firmware candidate

This target uses the architectural linen Study layout at 720 × 1280 on the Waveshare engineering-sample ESP32-P4 with 32 MB flash. The screen assets come from the repository's kiosk HTML. Use a private build directory outside the checkout. The generated assets describe the room, and the firmware and YAML contain per-device credentials.

## Build

Use Python 3.11 with ESPHome 2026.6.5, NumPy, Pillow and Playwright with Microsoft Edge. From the repository root, run:

    python esphome/study/render.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/firmware.py PRIVATE_BUILD
    python esphome/p4_runtime/prepare.py PRIVATE_BUILD config-export.json --id DEVICE_ID --mac DEVICE_MAC --server SERVER_URL
    python -m esphome compile PRIVATE_BUILD/study-live.yaml

The export contains a top-level `config` object. The renderer takes a JSON array of HA state objects. Rendering uses an isolated browser with fixture sockets. Keep private firmware, state exports and provisioning files out of Git.

## Device and server

Each P4 needs its own fleet identity and ESPHome encryption key. Run `python esphome/p4_runtime/enroll.py PRIVATE_BUILD/fleet-identity.json --ip DEVICE_IP` to register it with the server. Use an authenticated HTTPS origin for enrollment when available. The existing HTTP deployment requires a trusted provisioning network. Claim the new P4 in the dashboard and import the Study configuration used for rendering. Home Assistant needs a native ESPHome connection with the generated encryption key and permission to perform HA actions.

The candidate downloads authenticated, signed configurations, keeps the last verified room profile in NVS and subscribes directly to HA light states. It can apply changes to Soft, Bright and preset participation. A configuration change that requires new artwork needs a new render. The worker starts after Ethernet connects. Touch navigation starts locally.

The normal ESPHome upload writes only the application images. This target also needs its matching motion bank and acceleration table. The fixed layout has two 3 MiB application slots, a motion partition starting at 0x610000 and NVS at 0x1f90000. The generated `live_runtime/motion_tail.h` gives the byte offset of `live-motion-tail.bin` within the motion partition. Verify the identity, partition table, space and image digests before installing. Preserve the previous working image.

## Coverage

Live bindings currently cover native HA light details and Soft, Off and Bright scene actions. The other captured screens include fixture values. Open release items include dynamic dashboard widgets, advanced light and media workflows, settings persistence, local DALI, fleet update delivery and production doorbell video. This branch is for testing on a separate P4.
