# Pi kiosk OS: findings

Companion to `docs/P4-FINDINGS.md`. That doc's "lighter OS/compositor"
theory was tested once, inconclusively, and flagged for a clean redo. This
doc is that redo's setup -- fill in the Results table once it's actually run
on hardware.

## Open question this closes

> "A lighter OS/compositor will help the Pi" -- `cage` tested no better than
> the desktop session. (Caveat: the test ran nested over a live desktop, so
> it wasn't clean. Redo properly before relying on the result.)
> -- docs/P4-FINDINGS.md

## Suspected confounds in the original test

- **Nested compositor.** Running `cage` inside an already-running desktop
  session means it's compositing inside another compositor -- extra copy,
  extra scheduling, no representative GPU/DRM access. That alone could erase
  a real difference in either direction.
- **Ozone/Wayland not confirmed.** Chromium only renders natively via
  Wayland/DRM if told to (`--ozone-platform=wayland`, see
  `pi-os/kiosk-launch.sh`). Without it, a Chromium build can silently fall
  back to XWayland (not present under a bare `cage` session, so this would
  fail visibly) or software rendering (which would *not* fail visibly, and
  would produce exactly a "no better than desktop" result for an unrelated
  reason). Check `chrome://gpu` inside the session before trusting any
  number from either run.

## Clean test setup

- Raspberry Pi OS Lite -- no desktop environment installed at all, not
  "desktop present but unused."
- `cage` launched via `pi-os/cage-kiosk.service`, i.e. the real boot path,
  not started manually from a shell.
- Cold boot before each measurement. No SSH session held open during
  measurement -- an active logind session changes seat arbitration and is
  not the target condition.
- Confirm `chrome://gpu` shows hardware acceleration active on both the
  `cage` run and whatever desktop-session baseline it's compared against,
  so a driver-fallback difference doesn't get mistaken for a compositor
  difference.

## Measuring

`panel.html`'s glass-tier toggle (see CLAUDE.md) already exists for this
A/B. Pair it with `pi-os/fps-meter.js` -- paste into the page console, or
wire behind a temporary `?fps=1` query flag -- which logs rolling average
FPS once a second.

Run each combination for at least 60s of normal panel use (not idle): glass
on / off, under `cage`, under whatever desktop-session baseline is being
compared against.

## Results

| Config | Avg FPS | Notes |
|---|---|---|
| Desktop session, glass on | -- | fill in |
| Desktop session, glass off | -- | fill in |
| `cage`, glass on | -- | fill in |
| `cage`, glass off | -- | fill in |

## Status

Not yet run. This doc defines the test; `docs/P4-FINDINGS.md`'s note stays
authoritative ("don't rely on it") until the table above is filled in on
real hardware.
