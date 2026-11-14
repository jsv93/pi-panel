# Architectural P4 acceptance

Hardware: Waveshare ESP32-P4 Wi-Fi 6, 32 MB flash, 5-inch 720 × 1280 DSI,
microSD and Wi-Fi. Reference: the CM5 kiosk's Chromium renderer captured at
720 × 1280. Date: 15 November 2026. The working CM5 was not reflashed.

This records measured behavior, rather than claiming pixel-identical rendering
or equating the display's approximately 55 Hz refresh with rendered frames.
RGB565 and intermediate JPEG motion frames differ from Chromium compositing.

The screen captures and input replays below used the instrumented candidate.
The final production build uses the same panel runtime without its QA actions.
Panel Server 0.27.2 built and installed generation 216847794, configuration 435,
on the physical P4. Its normal encrypted API, live camera, Identify, telemetry
and server-offline hardware restart were checked again after installation.

| Area | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Main screens | 15 full-resolution captures online and offline; mean absolute channel error 2.41–3.27/255 against current CM5 captures | Candidate passed; production boot/API smoke passed |
| Page navigation | 101/101 routes completed online and offline; user confirmed stripes gone and colour steady | Passed |
| Home zoom | 60 online runs across six palettes and 20 offline runs across two; bounded DMA copies removed the measured long endpoint stall | Passed |
| Popups | 36 online runs across six palettes; eight presented frames in 174–181 ms, approximately 45 fps; popup controls also exercised offline | Passed |
| Palette/control artwork | 66 overlay captures online, 22 offline; matching geometry and palette colours; hardware-specific network values differ | Passed |
| Lights | Five live brightness settings confirmed by HA online and offline; stale-state bounce fixed; original level restored | Passed |
| Music | Playing capture checked; blue rectangle fixed; continuous progress uses actual rendered-frame measurement | Passed on instrumented candidate |
| Speaker picker and transfer | Real transfer completed online and offline; original target, volume, queue and elapsed position restored | Passed |
| Music library | Browse and playback passed online and offline; an initial malformed HA browse response required one retry; player restored | Passed |
| Presets and membership | Save/read-back/restore passed | Server-owned edits intentionally require server |
| Wi-Fi | Existing encrypted HA identity and saved station retained across firmware updates and the production hardware restart | Passed |
| Doorbell | Study Echo direct MJPEG passed online and offline, around 2–4 fps; standby/wake checked; production displayed 24 live frames in each final test | Passed; camera limits apply |
| Fleet diagnostics and Identify | Production rejoined after outage; live temperature, CPU and RAM samples resumed; idle render FPS was 0 while DSI refresh was 55 Hz; normal server Identify reached the P4 | Passed |
| Automatic deployment | Signed per-device encrypted application/artwork OTA, byte-range resume at byte 333333, failed-health rollback to prior valid slot passed; real HA add-on rendered, compiled and installed the production release | Passed |
| Linux builder | Final recovery revision passed Docker build, auth/isolation tests and complete synthetic room render/compile in GitHub Actions | Passed |
| HA virtual CPU compatibility | Live build exposed NumPy 2.4's x86-64-v2 requirement; compatible NumPy 2.3.5 passed import and five full-resolution RGB565 colour cases under QEMU's legacy CPU profile; live HA rendering then started successfully | Passed |
| Build configuration changes | Temporary P4-only room edit cancelled the active build; restoring Study cancelled that intermediate build and queued configuration 435 automatically | Passed |
| Offline boot | Clean firmware rebooted with Panel Server and PC update services stopped; retained signed configuration, palette and local artwork; direct HA reconnected | Passed |
| SD recovery | Deliberately withheld card access for 15 seconds; management remained reachable; native rendering and all banks recovered automatically; healthy boot confirmed | Passed |

The final production application is 3,013,456 bytes. Both Panel Server and the
temporary PC update bridge were confirmed unreachable before the final hardware
reset, which wrote no flash. The P4 booted and played the Echo camera through HA.
Panel Server was restored afterward; the P4 reconnected and reported its local
display/artwork healthy. Automatic updates remain enabled and the PC bridge is
stopped. The production API exposes only `ring`, `frame`, `close` and
`ring_live_camera`.

After the final rejoin, the server measured 35.4 °C, approximately 1.9% CPU and
87.25% RAM usage at idle. These are observations from this device, not performance
guarantees. GitHub release validation includes a legacy x86 virtual-CPU rendering
test as well as native amd64/arm64 image builds. Private firmware, room configuration
and artwork are not uploaded to GitHub.

## Scope and dependencies

Architectural and its six palettes are the accepted theme scope. Other themes
and the standalone scroll benchmark are excluded by agreement. DALI/Luna
hardware acceptance is deferred until infrastructure exists. The unavailable
Study thermostat prevents a physical setpoint test; its unavailable state is
covered. These are not recorded as hardware passes.

Home Assistant remains necessary for live controls and the Echo camera. Panel
Server is necessary for new configuration/artwork builds, central history and
remote fleet actions, server-owned edits, and uncached provider-logo conversion.
The local room, palettes and motion artwork live on the P4/card. See
[deployment and offline behavior](P4-DEPLOYMENT.md).
