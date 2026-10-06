# Architectural theme

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

Use the existing release workflow: the `v0.11.0` tag must match the add-on
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
