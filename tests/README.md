# Tests

    stub_dali_gateway.py   a Lunatone DALI-2 IoT gateway, to the shapes in
                           Lunatone's API documentation M0023
    test_dali_client.py    exercises the agent's gateway client against it
    test_slider_drag.html  the slider's drag/state race, in a browser
    test_hacs_layout.py    the repo layout HACS needs, checked here rather
                           than at install time in someone else's HA

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
