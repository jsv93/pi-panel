# P4 interaction follow-up

Scope: Architectural Study interaction fixes for 0.27.4 (including 0.27.3). Library scrolling,
artwork caching and the reported colour wave remain separate work.

The focused instrumented P4 check on 15 November 2026 covered:

- Mini-player: 55 presented frames/second and twelve different sampled bar
  images. Geometry and the four animation periods were compared with an
  isolated 720 × 1280 Chromium session on the working CM5. Bars grow from the
  bottom, matching its CSS transform origin.
- Scene selection: immediate requested selection, stable throughout three
  live HA scene changes, with a 180 ms selection surround transition.
- Colour temperature: immediate requested value and twenty subsequent live
  readings without reverting to the previous value. Original lights restored.
- Standby: both clock and black-screen entry/wake. Backlight traces confirm
  that a wake from black only illuminates Home. Production additionally waits
  for the backlight write acknowledgement, a submitted destination frame and
  two display refresh boundaries.
- Scene participation: saved, read back and restored. Full-resolution before
  and after captures have zero pixel changes in the surrounding page margins,
  title and footer.
- Existing Home/Lights/lamp animation bank retained. Sample Home-to-Lights
  presentations occurred at 42, 56, 68, 85, 102, 120, 139, 157, 175 and 202 ms;
  the sampled lamp entry presented ten frames, finishing at 238 ms.
- Existing update isolation, signed configuration and artwork-service checks
  pass.

The automatic-build follow-up exposed a palette rank above the old byte limit.
Exact exceptional colours now live in a sparse table while the working rank
buffer remains one byte per pixel. The captured six-palette case had 113
exception pixels across seventeen pages; every full-resolution colour mapping
was checked against its source capture. An exception only applies when its
original source pixel still matches, so changing live text is not overwritten.

These checks cover the candidate runtime. They do not claim that library
scrolling, all animation colour handling or the complete panel is identical to
Chromium. Private diagnostic actions are excluded from production firmware.

Physical follow-up confirmed smooth mini-player bars and black-screen wake.
Clock entry now crossfades for 180 ms without dropping the backlight to zero;
the user confirmed the crossfade looks good.

The user still saw a full-screen blue flash on membership saves even though
framebuffer captures were unchanged outside the checkbox. The display DMA
restart interrupt was not cache-safe during the offline configuration's NOR
flash writes. The follow-up enables IDF's cache-safe DSI path and places the
remaining display callback in internal executable memory. On the candidate,
six saved membership changes had a maximum DMA refresh interval of 18,194 us
and no reported underruns. The existing transition artwork and timing are
unchanged.

The user confirmed the full-screen blue flash is gone on this build. Repeated
focused checks passed with the server online. With Panel Server stopped, the
P4 retained local artwork, direct HA connectivity, 55 presented mini-player
frames/second, clock entry/wake, and a stable 5170 K colour-temperature request.
Original light settings were restored and Panel Server was restarted.

Production rollout completed through the 0.27.4 GitHub release image and the
server's per-device signed/encrypted updater. The automatic builder passed
palette packing and firmware compilation, and the panel reported its local
display and artwork healthy. The production API exposes only `close`, `frame`,
`ring` and `ring_live_camera`; the private test action is absent.

The installed production firmware also booted with both Panel Server and the
temporary PC update bridge stopped. After restarting Panel Server, the fleet
again reported the panel live, HA connected and the production artwork healthy.
The PC bridge and temporary administrator sessions were closed.
