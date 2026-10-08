# Tests

## RAM diagnostics

    python tests/test_ram_metrics.py

Needs the server requirements and httpx. Reads temporary `/proc/meminfo`
fixtures through the actual agent, checks available-memory calculations and
missing/invalid readings, then verifies that a real server heartbeat preserves
the numeric RAM metrics for the admin UI.

## Architectural theme

    python tests/test_theme_display.py
    python tests/test_media_compatibility.py
    node tests/test_architectural_theme.cjs

The Python check needs the server requirements and httpx. The browser check
needs Playwright in the development environment only; set `PLAYWRIGHT_CHANNEL`
to `msedge` to use installed Edge, or install Playwright Chromium. Optionally
set `SCREENSHOTS_DIR` to save screenshots. It uses stubbed HA/agent responses,
exercises both navigation visibility settings and all three themes, and runs
the existing slider drag regression test against the shipped HTML.

The media admin browser check uses the real server under the ingress prefix,
with deterministic HA entities. Set `PANEL_DB` to a scratch database and
`ADMIN_PASSWORD=local-qa-only`, start
`python -m uvicorn serve_media_under_ingress:outer --app-dir tests --port 8877`,
then run `node tests/test_media_admin.cjs`. It verifies compatibility labels,
selection, refresh without losing edits, saved settings, and RAM diagnostics
including zero usage and missing readings from older agents.

    stub_dali_gateway.py   a Lunatone DALI-2 IoT gateway, to the shapes in
                           Lunatone's API documentation M0023
    test_dali_client.py    exercises the agent's gateway client against it
    test_slider_drag.html  the slider's drag/state race, in a browser
    test_hacs_layout.py    the repo layout HACS needs, checked here rather
                           than at install time in someone else's HA
    serve_under_ingress.py runs the config server under an ingress path,
                           which is how it actually runs

The stub exists because the client had to be written before the hardware
arrived, and because it can be made to misbehave in ways the real gateway
cannot be asked to on demand: `POST /_push/0` stops it announcing changes,
which is the open question in `docs/DALI-INTEGRATION.md`, and `POST /_bus/0`
reports the DALI supply as dead.

Run it:

    pip install fastapi uvicorn aiohttp
    python -m uvicorn stub_dali_gateway:app --port 8830 &
    python test_dali_client.py <scratch-dir> http://127.0.0.1:8830 ../agent/panel-agent.py

18 checks. The stub is not a conformance test — it is only as right as the
manual, and the manual is wrong about at least one thing.

## test_slider_drag.html

Serve this next to a copy of `panel.html` and open it. It lifts `slider()` out
of the page at run time and drives it, so it tests the shipped source rather
than a copy that can drift out of step with it.

    cp ../panel-ui/panel.html .
    python -m http.server 8840

12 checks: external state arriving mid-drag, a long hold with state arriving
throughout it, that external state is believed again the moment the finger is
off, and that a cancelled touch does not leave the slider deaf to updates for
the life of the page.

## test_hacs_layout.py

    python tests/test_hacs_layout.py

No dependencies. Checks the things HACS is silently strict about: `hacs.json`
at the root, exactly one directory under `custom_components/`, the manifest keys
it needs, that the domain matches its directory, that the version has moved off
the scaffold default (it never offers an update otherwise), and that every
platform the integration declares has a file behind it.

## serve_under_ingress.py

    PANEL_SERVER_DIR=../server PANEL_DB=/tmp/x.db ADMIN_PASSWORD=testpw       python -m uvicorn serve_under_ingress:outer --port 8851
    # then open http://127.0.0.1:8851/api/hassio_ingress/testtoken/

Home Assistant serves the add-on from `/api/hassio_ingress/<token>/`, never from
the root. Running it at the root during development hides a whole class of bug:
an absolute `/api/...` path in the GUI is correct there and 404s against Home
Assistant itself once it is behind ingress. That is exactly how Export shipped
broken. Anything touching a URL in `index.html` is worth a minute here.
