# Tests

    stub_dali_gateway.py   a Lunatone DALI-2 IoT gateway, to the shapes in
                           Lunatone's API documentation M0023
    test_dali_client.py    exercises the agent's gateway client against it

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
