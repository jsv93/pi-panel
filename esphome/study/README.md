# Study firmware candidate

This target uses the architectural linen Study layout at 720 × 1280 on the Waveshare engineering-sample ESP32-P4 with 32 MB flash. The screen assets come from the repository's kiosk HTML. Use a private build directory outside the checkout. The generated assets describe the room, and the firmware and YAML contain per-device credentials.

## Build

Use Python 3.11 with ESPHome 2026.6.5, NumPy, Pillow, LZ4 4.4.4 and Playwright with Microsoft Edge. From the repository root, run:

    python esphome/study/render.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/control_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/media_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/text_art.py config-export.json states.json PRIVATE_BUILD
    python esphome/study/firmware.py PRIVATE_BUILD
    python esphome/p4_runtime/prepare.py PRIVATE_BUILD config-export.json --id DEVICE_ID --mac DEVICE_MAC --server SERVER_URL
    python -m esphome compile PRIVATE_BUILD/study-live.yaml

The export contains a top-level `config` object. The renderer takes a JSON array of HA state objects. Rendering uses an isolated browser with fixture sockets. Keep private firmware, state exports and provisioning files out of Git.

For a paired Architectural-only panel, render the text artwork with `text_art.py --architectural-only`, build the six-palette bank described below, and pass `--hosted-wifi --architectural-only --production` to `prepare.py`. The base pages and palette bank reside in onboard flash. Palette-specific overlays use the card package described below. The diagnostics page retains its live readings and connection badges. The standalone scroll benchmark is omitted. Generate the artwork for the same room export used for enrollment.

### Architectural overlays

Capture the library, speaker picker, queue, Wi-Fi picker, music text, light-detail sheets and volume controls with the same browser and fonts used for the CM5 comparison. `overlay_capture.py` accepts an optional `--chromium-cdp` loopback endpoint for an isolated Chromium instance on the CM5. It generates a subdirectory for each of the six Architectural palettes.

    python esphome/study/overlay_capture.py config-export.json states.json PRIVATE_CAPTURES --chromium-cdp http://127.0.0.1:9222

Copy `PRIVATE_CAPTURES/linen/text_art.h` and `text-art.bin` into `PRIVATE_BUILD`, then pack the overlays against that native text bank and the existing control headers.

    python esphome/study/overlay_art.py PRIVATE_BUILD PRIVATE_CAPTURES PRIVATE_OVERLAYS --controls PRIVATE_CAPTURES

Copy the generated hash-named `.bin` file into the existing microSD card's `pi-panel` directory and pass `--overlay-assets PRIVATE_OVERLAYS` to `prepare.py`. Keep the card inserted during use. The firmware verifies the package SHA-256, loads it locally after boot and caches frequently reused patches. The artwork remains available when Panel Server is offline. The packer checks the captured geometry and font metrics, and `prepare.py` verifies that the overlay index matches the native text bank.

Provision the generated application, `text-art.bin` and `palette-art.bin` together using the offsets and hashes in the new `live_runtime/motion_tail.h`. A changed text-bank size can move the palette bank. Preserve the previous application and its matching banks for rollback. Card packages have immutable hash-based filenames so both application versions can retain their own artwork.

### Architectural navigation on microSD

Generate the full-resolution navigation package from the same six-palette captures used for the page bank.

    python esphome/study/sd_navigation.py PALETTE_DIRECTORY PRIVATE_NAVIGATION

Copy the generated hash-named `.bin` file into the card's existing `pi-panel` directory, then pass `--navigation-assets PRIVATE_NAVIGATION` with `--architectural-only` to `prepare.py`. Provision the complete file before installing the matching application. `navigation.json` records its exact storage requirement and SHA-256. Identical destination fades share frames; the current Study package uses approximately 70 MB in addition to the overlay package. Keep the card inserted for local navigation artwork during a Panel Server outage.

The firmware checks the complete package SHA-256 in a background task after boot. Its frame index and native RGB565 page hashes keep live controls, text and album artwork in the transitions. The reader combines adjacent sectors within FatFs's allocation map and shares the filesystem volume lock with other card operations. Existing fragmented files and allocation sizes are supported. Missing or invalid artwork uses the existing compositor while the loader retries.

Transition frames decode at 720 × 1280. The incoming page fades up against the palette's dark ground and scrim, using the CM5's 180 ms ease-out and slight horizontal movement. The outgoing page is excluded, including its live text and artwork. Changed incoming regions blend through the P4 graphics accelerator. The first frame is prefetched while preparing the destination page. The SD build wraps ESP-IDF 5.5's DSI DMA callback registration to retire framebuffers after their actual DMA completion; unrelated DMA clients retain their original callbacks. Revalidate this driver contract before changing the IDF minor version. If tracking is unavailable, the renderer retains its conservative two-refresh retirement rule.

The current six-palette Study package occupies about 67 MiB. Full integrity verification runs after each cold boot; navigation remains usable through the existing compositor meanwhile. Animation artwork is JPEG-compressed, while settled pages retain their native RGB565 rendering. The fade uses the settled scrim colour, and does not reproduce the browser's separate Home scale animation. Live album blending and non-Linen destination preparation can still increase frame time and initial response latency.

### Card-backed artwork in the candidate

The Default and Ambient comparison uses 720 × 1280 RGB565 captures from Chromium on the CM5. For each theme and palette, `card_art.py` reads `screens.bin` and `screens.json`, plus the theme's `geometry.json` measured at the same viewport. `card_light_art.py` renders brightness tracks and percentages at every level from 0 through 100. Its `--chromium-cdp` option accepts a loopback SSH forward to an isolated Chromium instance on the CM5. Use the same browser and fonts for both captures.

Use the same private destination for the generators. `card_scene_art.py` captures the active and inactive Home and Scenes preset buttons. `card_fields.py` captures the backgrounds and font data for live text. Copy the generated `pi-panel` directory onto the microSD card and pass the destination containing the generated headers to `prepare.py --card-assets`. The card can contain other files. The firmware mounts its existing FAT filesystem with formatting disabled and verifies each artwork file against its compiled SHA-256 digest.

Run `card_climate.py` for the Climate digits and raised units, `card_speaker_art.py` for the room’s speaker rows, `card_player_art.py` for transport and theme choices, and `card_library_art.py` for library tiles and lists. `card_settings_art.py` renders Settings with diagnostics on and off, including all 101 backlight levels. `card_wifi_art.py` captures the network picker at each sheet height and both touch keyboard layouts. Give the generators the same private config, HA states and destination directory. Copy the resulting `pi-panel` folder to the card and rebuild the firmware with the matching headers.

`card_overlay_art.py` captures the room’s light-detail sheets, playback volume, queue and Home player. `card_scene_editor.py` captures the preset editor and membership controls. `card_diagnostics.py` measures the diagnostic labels. `card_doorbell.py` captures the camera viewport, button and status messages in all three themes. These use the same config, states, destination and optional `--chromium-cdp` arguments. Card files have content-addressed names, so an older application can continue using its own artwork during an upgrade.

Run `card_motion_geometry.py CONFIG STATES DEST/card_motion_geometry.h` with the same Chromium viewport to capture the Home equalizer and empty Wi-Fi screen positions. Use `prepare.py --production` for a paired panel. This build exposes the encrypted doorbell controls and omits the navigation and lamp demonstration actions.

The card build binds Lights sliders to HA, preset buttons to the room’s lamp levels, and the Home clock to HA time. The Climate and speaker pages use live HA data. The local player build includes the on-screen theme choice in Settings → Display, Music transport and library navigation. The kiosk’s theme and palette identifiers are also accepted in signed configuration updates. The local selections persist during a server outage. Keep test firmware on the separate P4 until the remaining overlays, settings, transitions and live states pass the CM5 comparison.

## Device and server

Each P4 needs its own fleet identity and ESPHome encryption key. Run `python esphome/p4_runtime/enroll.py PRIVATE_BUILD/fleet-identity.json --ip DEVICE_IP` to register it with the server. Use an authenticated HTTPS origin for enrollment when available. The existing HTTP deployment requires a trusted provisioning network. Claim the new P4 in the dashboard and import the Study configuration used for rendering. Home Assistant needs a native ESPHome connection with the generated encryption key and permission to perform HA actions.

The candidate downloads authenticated, signed configurations, keeps the last verified room profile in NVS and subscribes directly to HA light states. It can apply changes to Soft, Bright and preset participation. A configuration change that requires new artwork needs a new render. The worker starts after Ethernet or Wi-Fi connects. Touch navigation starts locally.

The enrolled device also opens an authenticated outbound WebSocket to Panel Server. It accepts Identify, wake, sleep, reload and restart actions. HTTPS server URLs use WSS with certificate validation. Every five seconds the panel reports its temperature, CPU usage, memory, uptime, actual rendered frames and display refresh rate. The server retains its per-device authorization and administrator controls.

The normal ESPHome upload writes only the application images. This target also needs its matching motion bank, acceleration table and volume artwork. The fixed layout has two 3 MiB application slots, a motion partition starting at 0x610000 and NVS at 0x1f90000. The generated `live_runtime/motion_tail.h` gives the offsets of `live-motion-tail.bin` and `volume-art.bin` relative to the start of the motion partition. Provision the volume bank at `0x610000 + volume_offset` and verify its SHA-256 against `volume_sha`. The previous paired build does not use those sectors. Verify the device, partition layout and digests before installing. Preserve the previous working image.

The Wi-Fi candidate uses the onboard ESP32-C6 on the Waveshare ESP32-P4-WIFI6-POE-ETH. Pass `--hosted-wifi` to `prepare.py` after regenerating the motion bank and text art. This build also requires `text-art.bin` at `0x610000 + text_offset`. Its compact motion index moves the acceleration and volume offsets. Back up the entire current motion partition with its application before swapping builds. Restore both together when reverting. Preserve the NVS partition. The firmware checks the external text asset digest before drawing the panel.

## Coverage

Live bindings cover native HA light details, individual and group power, current climate readings and thermostat controls. Scene highlights follow confirmed HA levels with the kiosk's two-point tolerance. The initial Study speaker supports play, pause, previous, next, shuffle and repeat over the direct HA connection. Soft and Bright levels and participating lights use per-device server writes. A stopped server leaves the last signed profile active. Failed edits are shown on the panel and are discarded. The Display slider commits on release and overrides adaptive brightness for ten minutes. Standby uses the configured idle and blank intervals, HA time and ambient light. A wake touch is consumed before the underlying controls receive input.

The light More sheets expose the captured effects, warmth, colour and preset membership for each configured light. The volume popup and transport controls operate on the configured speaker over its Home Assistant connection.

An admin test ring uses the paired device’s long poll. Panel Server retrieves the configured Home Assistant MJPEG stream and transcodes frames for the P4. If the server is unreachable, the panel can request that camera’s MJPEG stream directly with a camera-specific playback credential received through its encrypted ESPHome subscription. A direct ring then requires the configured HA trigger or the encrypted `ring_live_camera` action. A source that provides only WebRTC or HLS needs a separate video path.

The relay preserves the camera aspect ratio. The P4 fits each frame into the video rectangle measured from the kiosk HTML and draws the status and duration from the same layout. If a server stream ends during a ring, the same overlay can continue from Home Assistant.

The Home player and Music screen use the configured speaker’s HA title, artist, position and duration. The seek action is available when the speaker reports support. The queue shows the current track and reported playlist or album. The panel can decode baseline JPEG cover art from the configured HA host, including a Music Assistant image endpoint on that host. The Home artwork preference persists on the device.

The Music screen lists the configured speakers and switches its transport, volume, timeline and artwork to the selection. Queue transfer uses the Music Assistant action and waits for Home Assistant to confirm. The destination needs an available Music Assistant player with a different queue. The library browses Home Assistant directly, pages through large folders, and offers tile and list views. Selecting a playable track sends it to the selected speaker. The library view preference persists locally. Visible items can load baseline JPEG thumbnails over HTTPS or from the HA host. Home Assistant provider PNG logos use the enrolled image endpoint in Panel Server 0.26.3 and preserve transparency across palettes. The P4 keeps up to twelve converted logos in a bounded NVS cache for offline browsing and cold boots. A new or evicted logo needs the server once. Other PNG URLs, signed relative thumbnail paths and unsupported image sizes retain the kiosk fallback icon.

The room menu date, Home Assistant connection, network, backlight and uptime readings come from the P4. Enabling diagnostics places the HA connection and the number of frames presented during the last second in the top corners. A stationary page reports zero rendered frames. Panel Server displays the physical refresh rate separately. The preference persists across restarts.

The Architectural firmware includes six native colour choices under Display → Theme colours when built with the palette bank. The picker and the saved selection run locally, including after a reboot. Default and Ambient load their page layouts from the card. The Network screen in the hosted Wi-Fi candidate scans the 2.4 GHz band and accepts an SSID selection and a passphrase on its touch keyboard. The worker waits for authentication and a DHCP lease before saving a new network.

To include the picker, render each Architectural palette into a subdirectory named after its palette. Keep each render's input configuration in that directory as `config.json`. Run the following commands before `prepare.py --hosted-wifi`.

    python esphome/study/palette_art.py PALETTE_DIRECTORY PRIVATE_BUILD/study-palettes.bin
    python esphome/study/palette_runtime.py PALETTE_DIRECTORY PRIVATE_BUILD/study-palettes.bin states.json PRIVATE_BUILD

The second command checks all resting screens against the CM5 RGB565 captures and captures all six picker states. Provision `palette-art.bin` at `0x610000 + palette_offset` from the generated motion header. The app verifies its digest. Non-Linen movement uses the P4 compositor unless the matching SD navigation bank is ready. Live media, overlaid text and transition colours still require visual comparisons on the device.

## Hardware test

`tests/p4_study_touch.py PRIVATE_BUILD` generates a bench-only firmware configuration. The fixture light and thermostat clients exercise the regular touchscreen handlers without forwarding actions to the house. The default fleet destination is an unreachable loopback endpoint and uses the existing signed cache. The optional `--fixture-identity` selects a separate disposable server, credentials and NVS namespace for authenticated write and subsequent outage tests. Never deploy this image as the panel firmware. Restore and verify the paired image after testing.

`tests/p4_study_inventory.py` compares visible kiosk touch targets with the native hit regions. `tests/p4_study_numbers.py` measures RGB565 readout differences against Chromium. A matching touch rectangle alone only establishes reachability.

Pass `--capture` to the touch replay generator to export the actual 720 × 1280 framebuffer when each page settles. Save the USB log locally. Run `python tests/p4_study_capture.py PRIVATE_BUILD usb.log PRIVATE_FRAMES` to reconstruct every pixel and check the board's CRC for each view. The captures contain room information.

For a comparison with real Home Assistant readings, first generate the bench configuration with a separate fixture identity. Run `python tests/p4_study_live_views.py PRIVATE_BUILD` and compile the resulting `study-views.yaml`. This replay uses the panel's real HA state subscriptions. It navigates through the room, light sheets, Music popups and doorbell, then returns Home. Capture the UART at 1,500,000 baud through `LIVE_VIEWS_DONE`. Run `python tests/p4_study_capture.py --live PRIVATE_BUILD usb.log PRIVATE_FRAMES` to verify the captured frames. Use a separate run after stopping the test server and rebooting the panel. Restore the enrolled application when the comparison finishes.
