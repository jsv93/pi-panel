# P4 interaction follow-up

Scope: Architectural Study interaction fixes for 0.27.3. Library scrolling,
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
