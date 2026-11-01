"""Real TLS, certificate pinning, device proof and the actual agent loop.

Uses disposable localhost ports/data; no hardware actions or external services.
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time

import aiohttp
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from management_setup import create
from launch import configure


async def exercise(folder):
    data = folder / 'server'
    create('https://127.0.0.1:8449', 'operator', ['study'], data)
    options = json.loads((data / 'options.json').read_text())
    configure(options, data)
    bad = dict(options, management_panels=['*'])
    try:
        configure(bad, data)
        raise AssertionError('Wildcard should fail')
    except ValueError:
        pass
    agent_dir = folder / 'agent'
    agent_dir.mkdir()
    (agent_dir / 'panel-id').write_text('study')
    os.environ.update(PANEL_DIR=str(agent_dir), PANEL_SERVER='http://127.0.0.1:8099')
    spec = importlib.util.spec_from_file_location('test_agent', ROOT / 'agent/panel-agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    agent.metrics = lambda: {'browser_health': 'Healthy', 'cpu_temp': 53, 'ha_token': 'must-not-leak'}
    env = {**os.environ, 'PANEL_DATA_DIR': str(data), 'PANEL_DB': str(data / 'panels.db'),
           'ADMIN_PASSWORD': 'test-only', 'HA_URL': '', 'HA_TOKEN': '', 'SUPERVISOR_TOKEN': ''}
    log = (folder / 'server.log').open('w')
    process = subprocess.Popen([sys.executable, str(ROOT / 'server/launch.py')], env=env,
                               cwd=ROOT / 'server', stdout=log, stderr=log)
    task = None
    try:
        context = ssl.create_default_context(cafile=str(data / 'root.crt'))
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8099', timeout=10) as lan, \
                   httpx.AsyncClient(base_url='https://127.0.0.1:8449', verify=context, timeout=15) as secure:
            for _ in range(100):
                try:
                    if (await lan.get('/management/')).status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise AssertionError('server did not start')
            assert (await secure.get('/management/')).status_code == 200
            assert (await lan.get('/management/open?panel=study')).headers['location'] == 'https://127.0.0.1:8449/management/?panel=study'
            registered = await lan.post('/api/register', json={'panel_id':'study', 'hostname':'study', 'kind':'pi'},
                headers={**agent.server_headers(), 'X-Panel-Sign-Key': agent.SIGN_KEY})
            assert registered.status_code == 200, registered.text
            assert (await lan.get('/api/management-transport/study', params={'nonce':'a'*64})).status_code == 403
            payload = (await lan.get('/api/management-transport/study', params={'nonce':'a'*64}, headers=agent.server_headers())).json()
            assert agent.checked_management_transport(payload, 'a'*64)
            assert agent.checked_management_transport(payload, 'b'*64) is None
            changed = {**payload, 'origin':'https://attacker.example:8449'}
            assert agent.checked_management_transport(changed, 'a'*64) is None
            async with aiohttp.ClientSession() as s:
                try:
                    await s.ws_connect('https://127.0.0.1:8449/management/agent/study',
                        ssl=aiohttp.Fingerprint(b'\0'*32), headers=agent.server_headers())
                    raise AssertionError('wrong certificate accepted')
                except aiohttp.ServerFingerprintMismatch:
                    pass
                for headers, url in [
                    (agent.server_headers(), 'http://127.0.0.1:8099/management/agent/study'),
                    ({**agent.server_headers(), 'Origin':'https://127.0.0.1:8449'}, 'https://127.0.0.1:8449/management/agent/study'),
                    ({}, 'https://127.0.0.1:8449/management/agent/study')]:
                    try:
                        await s.ws_connect(url, ssl=context, headers=headers)
                        raise AssertionError('unauthorized websocket accepted')
                    except aiohttp.WSServerHandshakeError as e:
                        assert e.status == 403
                async with s.ws_connect('https://127.0.0.1:8449/management/agent/study', ssl=context,
                                        headers=agent.server_headers()) as ws:
                    await ws.receive_json()
                    await ws.send_json({'proof':'0'*64})
                    reply = await ws.receive()
                    assert reply.type == aiohttp.WSMsgType.CLOSE and reply.data == 1008
            key = (data / 'access-key.txt').read_text().strip()
            login_body = {'user':'operator', 'key':key, 'panel':'study'}
            origin = {'Origin':'https://127.0.0.1:8449'}
            assert (await lan.post('/management/api/session', json=login_body,
                headers={**origin, 'X-Forwarded-Proto':'https'})).status_code == 403
            login = await secure.post('/management/api/session', json=login_body, headers=origin)
            assert login.status_code == 200, login.text
            operator = {**origin, 'Authorization':'Bearer ' + login.json()['session']}
            async with aiohttp.ClientSession(headers=agent.server_headers()) as session:
                task = asyncio.create_task(agent.management_loop(session))
                for _ in range(6):
                    connection = await secure.post('/management/api/panels/study/diagnostic',
                        headers=operator, json={'operation':'connection'})
                    if connection.status_code == 200 and connection.json()['agent_tls']:
                        break
                    await asyncio.sleep(3.1)
                else:
                    raise AssertionError('pinned agent connection did not appear')
                await asyncio.sleep(3.1)
                health = await secure.post('/management/api/panels/study/diagnostic',
                    headers=operator, json={'operation':'health'})
                assert health.status_code == 200, health.text
                assert health.json()['metrics'] == {'browser_health':'Healthy', 'cpu_temp':53}
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                task = None
            assert (await secure.post('/management/api/logout', headers=operator)).status_code == 200
            print('PASS native TLS, trusted certificate, pin mismatch rejection, nonce/signature validation, token+signing-key proof, real agent health, HTTP/header spoof denial, new-tab redirect')
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        process.terminate()
        process.wait(timeout=15)
        log.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temp:
        asyncio.run(exercise(Path(temp)))
