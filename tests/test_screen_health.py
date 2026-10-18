"""Behavioural checks; no real panel, service or HA instance is modified."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, AsyncMock
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]


def run(folder):
    os.environ.update(PANEL_DIR=str(folder), PANEL_DB=str(folder/'db'), ADMIN_PASSWORD='test-only')
    spec = importlib.util.spec_from_file_location('screen_agent', ROOT/'agent/panel-agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    sys.path.insert(0, str(ROOT/'server'))
    from app import main, db, screen
    from fastapi.testclient import TestClient

    # Time and service boundaries are simulated; production policy is exercised.
    with patch.object(agent.time, 'time', return_value=10000):
        agent.BROWSER_STARTED = 0
        assert agent.recovery_decision(119, {}) == ('Starting', None)
        agent.BROWSER_SEEN = 199
        agent.UI_STATE['ha_connected'] = False
        assert agent.recovery_decision(200, {}) == ('Healthy', None)
        agent.UI_STATE['screen_mode'] = 'blanked'
        assert agent.recovery_decision(200, {}) == ('Healthy', None)
        agent.BROWSER_SEEN = 1
        assert agent.recovery_decision(200, {'browser_recovery': False})[1] is None
        agent.PAGES.add('test')
        assert agent.recovery_decision(200, {})[1] == 'reload'
        agent.RECOVERY_STAGE = 1
        assert agent.recovery_decision(200, {})[1] == 'restart'
        agent.RECOVERY_LAST = 199
        assert agent.recovery_decision(200, {})[1] is None
        agent.RECOVERY_LAST = 0
        for _ in range(3):
            assert agent.record_recovery()
        assert len(json.loads(agent.RECOVERY_FILE.read_text())) == 3
        assert agent.recovery_decision(200, {})[1] is None
        agent.RECOVERY_ATTEMPTS[:] = [6000]
        assert agent.recovery_decision(200, {})[1] == 'restart'
        agent.PAGES.clear()
    print('PASS recovery: startup, HA outage, blanked screen, disabled mode, reload/restart, cooldown, durable hourly budget')

    for i in range(150):
        agent.browser_event('event '+str(i))
    assert len(agent.BROWSER_EVENTS) == 100

    async def diagnostic_test():
        ws = AsyncMock()
        with patch.object(agent, 'screen_settings', return_value={'remote_diagnostics': False}), \
             patch.object(agent, 'browser_cdp', new_callable=AsyncMock) as cdp:
            await agent.send_screen_diagnostics(ws, {'request_id':'x','capture':True})
            cdp.assert_not_called()
            assert 'error' in ws.send_json.call_args.args[0]
        with patch.object(agent, 'screen_settings', return_value={}), \
             patch.object(agent, 'metrics', return_value={'browser_health':'Healthy'}), \
             patch.object(agent, 'browser_cdp', new_callable=AsyncMock) as cdp:
            cdp.return_value={'data':'aGVsbG8='}
            await agent.send_screen_diagnostics(ws, {'request_id':'x','capture':False})
            cdp.assert_not_called()
            await agent.send_screen_diagnostics(ws, {'request_id':'x','capture':True})
            assert ws.send_json.call_args.args[0]['image']=='aGVsbG8='
            cdp.side_effect=RuntimeError('secret URL must not escape')
            await agent.send_screen_diagnostics(ws, {'request_id':'x','capture':True})
            value=ws.send_json.call_args.args[0]
            assert 'capture_error' in value and 'secret URL' not in json.dumps(value)
    asyncio.run(diagnostic_test())
    print('PASS diagnostics: disable switch, no unsolicited capture, image path, bounded events, safe errors')

    with TestClient(main.app) as client:
        assert client.post('/api/panels/test/screen-diagnostics', json={}).status_code==401
        client.post('/api/login',json={'password':'test-only'})
        # Provision from an old template, then from one made in another room.
        db.save_template('old-screen', {'display': {'theme':'architectural','palette':'linen'}})
        made = client.post('/api/provision', json={'room':'Living','template':'old-screen','brightness_sensor':'sensor.living_lux'})
        assert made.status_code == 200
        new = db.merged_config(made.json()['panel_id'])
        assert all(key in new['display'] for key in screen.DEFAULTS)
        assert new['display']['adaptive_sensor'] == 'sensor.living_lux'
        assert new['display']['adaptive_brightness'] and new['display']['browser_recovery'] and new['display']['remote_diagnostics']
        assert new['display']['theme'] == 'architectural' and new['bluetooth']['mode'] == 'on'
        db.save_template('other-room', {'display': {**screen.DEFAULTS,'adaptive_sensor':'sensor.other_room','adaptive_brightness':True,'browser_recovery':False,'adaptive_min_pct':15}})
        made2 = client.post('/api/provision', json={'room':'Bedroom','template':'other-room'})
        new2 = db.merged_config(made2.json()['panel_id'])['display']
        assert new2['adaptive_sensor'] == '' and not new2['adaptive_brightness']
        assert not new2['browser_recovery'] and new2['adaptive_min_pct'] == 15
        count = len(db.list_panels())
        for invalid in ['light.room', None, 5, {}, 'sensor.bad entity']:
            assert client.post('/api/provision',json={'room':'Invalid','brightness_sensor':invalid}).status_code == 400
        assert len(db.list_panels()) == count, 'invalid selection must not create orphan records'
        print('PASS provisioning: old/new templates, default diagnostics/recovery, explicit per-room lux binding, opt-outs, Bluetooth preservation, validation before creation')
        client.post('/api/register',json={'panel_id':'test','hostname':'test'})
        original={'lights':[{'entity_id':'light.room'}],'display':{'theme':'architectural','palette':'linen','background':{'mode':'room'}}}
        assert client.put('/api/panels/test/config',json=original).status_code==200
        update={**screen.DEFAULTS,'adaptive_brightness':True,'adaptive_sensor':'sensor.room_lux'}
        assert client.patch('/api/panels/test/display',json=update).status_code==200
        cfg=client.get('/api/panels/test').json()['config']
        assert cfg['lights']==original['lights']
        for key,value in original['display'].items():
            assert cfg['display'][key]==value
        for invalid in [{'adaptive_sensor':''},{'adaptive_min_pct':101},{'adaptive_dark_lux':301},
                        {'adaptive_transition_s':0},{'browser_stale_s':1},{'browser_recovery_limit':0},
                        {'browser_recovery':'false'},{'remote_diagnostics':1},{'adaptive_sensor':'light.room'}]:
            assert client.patch('/api/panels/test/display',json=invalid).status_code==400, invalid
            assert client.put('/api/panels/test/config',json={**cfg,'display':{**cfg['display'],**invalid}}).status_code==400, invalid
        assert client.post('/api/panels/test/screen-diagnostics',json={'capture':True}).status_code==503
        main.SCREEN_LAST_REQUEST.clear()
        # The real authenticated WS transports a correlated response. A mismatched
        # request id must not complete another administrator's pending request.
        with client.websocket_connect('/api/ws/test') as ws:
            ws.receive_json()
            with ThreadPoolExecutor() as pool:
                request=pool.submit(client.post,'/api/panels/test/screen-diagnostics',json={'capture':True})
                msg=ws.receive_json()
                assert msg['type']=='screen_diagnostics'
                ws.send_json({'type':'screen_diagnostics','request_id':'wrong','image':'bad'})
                ws.send_json({'type':'screen_diagnostics','request_id':msg['request_id'],'image':'aGVsbG8='})
                response=request.result(timeout=5)
                assert response.status_code==200 and response.json()['image']=='aGVsbG8='
                assert response.headers['cache-control']=='no-store'
        assert not main.SCREEN_REQUESTS
        assert client.post('/api/panels/test/screen-diagnostics',json={}).status_code==429
        client.patch('/api/panels/test/display',json={'remote_diagnostics':False})
        assert client.post('/api/panels/test/screen-diagnostics',json={}).status_code==403
    print('PASS server: authentication, validation, narrow save preserves design/assignments, WS correlation, rate limit and disabled/offline responses')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        run(Path(folder))
