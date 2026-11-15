# P4 interaction follow-up

## Motion and library candidate for 0.27.5

The 15 November follow-up compares the existing 720 × 1280 CM5 Chromium
layout with the P4's native rendering. It keeps the accepted clock crossfade,
black-screen wake and cache-safe display interrupts.

### Latest library, artwork and RAM refinement

The user confirmed that the whole-screen flash is gone and swiping is more
responsive. The next candidate uses rectangle DMA copies for library scrolling
and thumbnail updates; the page-transition renderer is unchanged.

- List/tile coasts present roughly 55 changing frames/s. Real album drags
  measured 39–48, versus roughly 33–40 before the rectangle copy. Two full-size
  scroll captures matched complete redraws exactly, with zero differing pixels.
- Warmed idle RAM measured 78.77% used, with 6.87 MiB free. The superseded lamp
  timeline occupied 4,951,232 bytes; it is now omitted only when both replacement
  SD fade routes exist. Library strings and thumbnail URLs use external RAM,
  protecting the smaller internal radio/DMA heap. HTTPS buffers also use PSRAM.
- Inactive Ethernet DHCP retries cleared global Wi-Fi DNS. Per-interface DNS
  retention and immediate active-lease restoration correct this without changing
  the user's resolver. Two bounded, unauthenticated HTTPS artwork connections
  retain certificate checks, close after five idle seconds, and are cancelled
  when leaving the library. The latest cold trace decoded 15 cached thumbnails
  by 12.4 seconds, without DNS or allocation errors. This is a cache count,
  not proof that every visible cover is instant; large external originals still
  take time on their first download.
- Home motion retained 22–23 ms maximum intervals between Home frames, and
  lamp transitions presented ten frames per pass. A source-page repaint before
  navigation can add a 65 ms preparation gap before the first Home frame; that
  gap is outside the fade and must not be counted as its motion cadence.

These figures describe the installed validation candidate. Public release
still requires the fresh production build; private probes are not shipped.
The final candidate also cold-booted with Panel Server and the PC bridge off.
Its transition/palette, real-album pagination, clock sleep/wake and exact-pixel
checks passed. Offline Home frame gaps were 22 ms; list/tile coasts reached
54–55 fps. Warmed offline idle was 77.98% RAM used, with valid Wi-Fi DNS and
zero underruns. Panel Server was restored and automated gestures stopped.

### Earlier candidate measurements

- Home handoff with the mini-player active: the corrected candidate's longest
  measured presentation gap was 22 ms from Lights and 23 ms from Music. The
  mini-player continued presenting 55 changing frames per second.
- Clock timeout: 20 decreasing backlight values over 380 ms within the 400 ms
  fade, followed by a black display; waking returned directly to Home.
- Music library: time-based momentum and touch-to-stop; real HA browsing of
  496 albums, forward pagination and reverse drags. The retained window and
  incoming window use external RAM. The fixed-heading sample stayed unchanged
  throughout the repeated drag, with at least 66,548 bytes of internal RAM free.
- Library rendering: copy the moving viewport and paint its newly exposed
  rows, keep headers coherent across all three buffers, and update arriving
  covers without repainting the entire library. Successful lookahead does
  not repaint already-visible rows. Isolated list/tile coasts measured about
  46–50 rendered frames/s; fast scripted drags with real artwork measured
  about 37–41. These are rendered frames, not the display's 55 Hz refresh.
- Artwork: bounded encoded and decoded caches, visible-cover priority and
  bounded lookahead; generated player pages use the normal empty-cover state.
  New artwork still depends on HA or its provider. Existing provider-logo
  caching continues to work without Panel Server.
- Transition colour: encode the stationary RGB565 dither at the hardware
  decoder's quantization levels. The sampled blurred room background had
  mean RGB error [0.92, 0.49, 0.02]/255 and 95th-percentile absolute error 2/255
  against the source image. Navigation retained 9–10 presentations in roughly
  180 ms across the tested light and dark palettes. Home frames are warmed
  into a bounded RAM cache; SD initialization negotiates high speed and retries
  at the normal clock if necessary.

These checks also passed after booting with Panel Server and the temporary
PC artwork/update services stopped, while HA remained connected. Panel Server
was restored afterward. Full-room Linux CI builds passed for both the original
candidate and the allocation/header correction. Rollout was held at this stage
for a whole-display flash and high-speed choppiness. The flash was subsequently
confirmed fixed, as recorded above.

Two fast-scroll captures in opposite directions matched complete redraws at
the same offsets exactly, with zero differing pixels. Sampled stationary
edge colours and headings stayed unchanged. A revised 100 ms touch-history
estimate produced 833 px/s for the slower test swipe and 2113 px/s for the
faster one, with endpoints of 529 and 905 px from an initial 300 px drag.
Holding before release stopped at 300 px without a fling. The whole-display
flash is being traced at the refresh/backlight level before release.

The display trace found DMA refresh intervals up to 35,767 us while scrolling.
IDF's framebuffer cache writeback held interrupts disabled across a full
viewport. Enabling its 16 KiB chunked writeback reduced the maximum observed
interval to 18,238 us in the same stress sequence (nominal 18,182 us). The
installed underrun hook was verified active and recorded zero underruns.
Display bus priorities remain at their original values. Real album pagination
and reverse drags still passed, with stable headings and no reset; fast drags
measured 36–40 rendered frames/s, and isolated list/tile coasts 45/48. Physical
confirmation that the remaining flash is gone is still pending.

This evidence does not establish identical Chromium scrolling performance or
prove that every physical fade is free of visible colour variation.

## Earlier 0.27.4 acceptance

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
