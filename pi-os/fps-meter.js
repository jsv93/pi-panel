// Paste into the panel's devtools console (chrome://inspect from another
// machine, since the panel itself has no visible devtools in kiosk mode), or
// wire behind a temporary `?fps=1` query check in panel.html. Logs a rolling
// average FPS once per second via requestAnimationFrame.
//
// This is a measurement tool for docs/PI-KIOSK-FINDINGS.md, not part of the
// shipped UI -- don't leave it wired into panel.html permanently.
(() => {
  let frames = 0;
  let last = performance.now();
  function tick(now) {
    frames++;
    if (now - last >= 1000) {
      console.log(`[fps] ${frames}`);
      frames = 0;
      last = now;
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
