# Architectural theme

## Music and hold-to-dim in 0.14.0

Music is the last bottom-navigation item. The home mini-player appears only
while the selected speaker is playing; idle and paused players remain reachable
through Music. Architectural artwork fills the available space above the title,
with seek/timing and transport together immediately above volume. Linen's enabled
shuffle/repeat controls have a filled cream background and dark icons.

The server's Media page labels entity choices with queue-transfer compatibility
and explains the selected speakers in a dedicated section. Music Assistant
entities are distinguished from native control-only entries; offline entities
and failed capability checks are not presented as supported. The service check
is cached for 30 seconds and never starts or transfers playback.

With the existing room-light gesture enabled, a three-finger tap toggles on
release. Hold for 600 ms to dim (the configured hold threshold may be increased
to 1500 ms; older shorter values use 600 ms). Release any finger to stop. The
first hold dims down, each subsequent hold reverses, and a hold from off brightens
gently. Stops are 1% and 100%, so a dimming hold never switches the room off.
Only available, dimmable scene members participate; lights already off stay off
unless the whole dimmable scene is off. Their relative brightness is retained
within the 1% floor. Tap-to-toggle and remembered levels remain available.

The ramp moves 4 percentage points every 200 ms with a single command batch in
flight and one replaceable pending batch. A slow connection cannot accumulate
an unbounded command backlog. Multi-touch cancels an underlying slider drag;
extra fingers, movement before the hold, touch cancellation and losing focus
stop the gesture. HA state echoes do not move held brightness values.

## Speaker transfer in 0.13.0

The speaker picker separates selecting a speaker (tap its name) from moving
playback (the arrow at its right). This works in all three themes. Transfer uses
Home Assistant's `music_assistant.transfer_queue` with an explicit source and
destination; playing queues continue playing, paused queues remain paused.
After HA accepts the action the player opens the destination. While pending,
repeat taps cannot submit another transfer. Errors stay in the speaker picker.

Both speakers must be Music Assistant entities, with an active queue on the
source. Offline, non-Music-Assistant and already-shared queues have disabled
transfer controls; their normal selection remains available. Configure the
Music Assistant version of a speaker in the server to enable its transfers.
External inputs without an active Music Assistant queue cannot be transferred.

## Warmer Linen in 0.12.1

Linen reduces green and blue relative to red in its text, surfaces, glass,
scene tint and placeholder artwork. The generic room background uses a more
strongly defocused image, embedded in the UI and shared with the server picker.
The blur is baked into the asset; no live filter or display-wide colour filter
is applied. Media artwork and colour-control values keep their original colours.

## Backgrounds and player in 0.12.0

Linen uses a stronger cream text and brown surface palette so its warmth is
more visible on the panel. The generic room image is now an abstract study of
warm light and planes, with no furniture or house-specific interior.

The player has larger, centred square artwork, transport controls below it,
and an icon-labelled volume slider directly above Speakers / Browse / Queue.
Shuffle and Repeat remain on the transport row and have been removed from
Playback options. Covers is available in the home navigation only. The sleep
screen shows its clock without a wake caption.

Theme and Theme colours open named selection lists in every theme. Opening a
list does not change the current choice, and the selected row is marked.

In the server, open a panel's **Display > Background** and choose Solid colour,
Uploaded image, Generic room or Generic pattern, then Save. JPEG, PNG and WebP
uploads are limited to 10 MB and 16 megapixels; the server converts them to a
still WebP with a maximum dimension of 1280px. Images are stored beside the
database in `backgrounds/` and included in the add-on data backup. A config
export references the image; keep the image file or use a full add-on backup
when moving servers.

Background selection is server-only. The panel cannot modify these fields
through its narrow display endpoint. Its agent caches the chosen upload
locally, verifies its hash against the signed config and retries a failed
download on later syncs. A missing image falls back to the built-in abstract
background; lighting configuration still applies. No live blur is added.

`tests/test_backgrounds.py` covers bounded decoding, invalid files, admin-only
writes, per-panel image access, ingress paths and agent cache integrity. The
browser tests cover selection lists across themes and player layout at multiple
panel sizes as well as the existing slider/state regression tests.

## Preview parity in 0.11.1

Architectural pages now use the preview's 180ms horizontal fade, including
light options, speakers, queue and network setup. Nested Back controls return
to the parent page. Reduced motion removes the entrance animation.

Scenes uses the same photograph, tint, rectangular glass controls and selected
underline as the approved preview. **Edit scene levels** opens the shared Soft
and Bright capture controls and a participating-light selector. Writes still
use the existing narrow `/presets` and `/light` agent endpoints, including
failure feedback and exclusions.

Lights now lists names, levels and individual power buttons. Selecting a name
opens its brightness page with a large readout, slider and step buttons; More
opens supported per-light options, with Colour one level deeper. Display and
Diagnostics have their own pages. The full music player includes Playback
options, outlined transport icons, a seek marker and volume step buttons.

For the preview's full-screen sub-pages, set **Navbar on sub-pages: Hidden**.
The visible-navigation preference is still supported when desired. Live room
names, available device capabilities, media artwork and readings naturally
replace the preview's demonstration content.

Hidden pages no longer retain layout space. Sliders refresh their geometry
when a page becomes visible, and keep drag coordinates correct when the 720px
stage is scaled to a smaller viewport. Regression tests cover external state
arriving during a brightness drag, capture failures, membership writes,
colour/effects, Playback options, nested Back navigation and theme switching.

Available in Panel Config Server 0.11.0. Select **Architectural** and the
**Linen** palette in a panel's Display settings. Theme and palette remain
independent; existing Default and Ambient installations keep their selection.

The home screen has a room heading, a temperature link to Climate, an
always-available media card, and Scenes / Lights / Climate / Covers navigation.
The ellipsis opens the room menu, including Settings and Standby. Soft, Off and
Bright live in Scenes. Off respects the same per-light exclusions as the other
presets. Covers retains the existing unconfigured placeholder; this release
does not add a blind entity mapping or service implementation.

Individual light controls, saved preset levels, exclusions, temperature and
colour controls, media browsing, queue, speaker selection and grouping,
thermostat adjustment, Wi-Fi, backlight, gestures, standby, diagnostics and the
scroll test use the existing shared UI and handlers. The existing navigation
visibility preference still applies on sub-pages.

## Assets and rendering

The generic room background is pre-blurred. Translucent surfaces use static
colour compositing, without `backdrop-filter`. Inter fonts and the WebP room
image are embedded in `panel.html`, so the existing agent's bundle allowlist
and offline cache need no changes. Licences are embedded in the HTML and copied
to `panel-ui/ARCHITECTURAL-ASSETS-LICENCE.txt`.

The four-bar playback indicator keeps the existing animation timings. It
pauses while a sheet covers it, while the panel is idle, or while the page is
hidden, and respects reduced motion. Progress uses `scaleX` in this theme.
Scrolling sheets retain their own compositing layer. Desktop browser checks
verify behaviour and layout, not the physical panel's frame rate; use Settings
> Diagnostics > Scroll test for hardware measurements.

## Release and recovery

Use the existing release workflow: the release tag must match the add-on
manifest. Confirm both architecture images and the add-on repository manifest
before updating Panel Config Server in HA. Confirm `/api/bundle-log` reports
`panel.html` from `image`; an operator file in `/data/bundle` overrides it.

The agent downloads the UI through the existing bundle sync and reload path.
Select the new theme with a narrow display patch, preserving entity mappings
and hardware settings. Compare the served bundle's SHA-256 with the committed
HTML, and check the panel's config acknowledgement and HA connection after
delivery. The agent's `ui_version` metric is an agent version, not a hash of
`panel.html`, so it cannot verify the UI release by itself.

To return to the previous appearance, select the previous theme and palette
(for Study: Ambient and Ember). A config-history rollback restores config,
not UI files. Restore the saved previous bundle or the add-on backup only if
the UI itself needs reverting.

## Validation

`tests/test_architectural_theme.cjs` exercises the shipped HTML against stubbed
HA and agent endpoints: scenes and exclusions, thermostat actions, media,
library, queue, menus, missing speaker configuration, reduced motion, multiple
viewport sizes, navigation visibility, and switching between all three themes.
It also runs the existing 12-case slider drag/state race regression harness.
No test sends commands to live devices.

`tests/test_theme_display.py` checks that the server accepts and persists the
new theme/palette while retaining unrelated config and rejecting invalid writes.
