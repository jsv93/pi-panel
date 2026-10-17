"""Scanner reconciliation never touches unrelated services or config."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


async def exercise(agent):
    unit = 'study-bt-proxy.service'
    state = {'LoadState': 'loaded', 'ActiveState': 'active', 'UnitFileState': 'enabled', 'MainPID': '0'}
    calls = []

    async def command(*args):
        calls.append(args)
        if args[0] == 'show':
            props = state if args[1] == unit else {'LoadState': 'not-found'}
            return args[1] == unit, '\n'.join(f'{k}={v}' for k, v in props.items()), ''
        assert args[1] == unit
        if args[0] in ('enable', 'disable'):
            state['UnitFileState'] = 'enabled' if args[0] == 'enable' else 'disabled'
        if args[0] in ('start', 'stop'):
            state['ActiveState'] = 'active' if args[0] == 'start' else 'inactive'
        return True, '', ''

    with patch.object(agent, 'bluetooth_command', command):
        assert (await agent.reconcile_bluetooth({}))['bluetooth_active']
        assert all(c[0] == 'show' for c in calls), 'legacy default must only observe'
        calls.clear()
        stopped = await agent.reconcile_bluetooth({'mode': 'off'})
        assert stopped['bluetooth_active'] is False and stopped['bluetooth_boot'] == 'disabled'
        assert [c[0] for c in calls if c[0] != 'show'] == ['disable', 'stop']
        calls.clear()
        await agent.reconcile_bluetooth({'mode': 'off'})
        assert all(c[0] == 'show' for c in calls), 'repeated config must be idempotent'
        calls.clear()
        started = await agent.reconcile_bluetooth({'mode': 'on'})
        assert started['bluetooth_active'] and started['bluetooth_boot'] == 'enabled'
        assert [c[0] for c in calls if c[0] != 'show'] == ['enable', 'start']
        state['ActiveState'] = 'failed'
        calls.clear()
        assert 'Failed' in (await agent.reconcile_bluetooth({'mode': 'on'}))['bluetooth_status']
        assert all(c[0] == 'show' for c in calls), 'do not defeat systemd start limiting'
        calls.clear()
        try:
            await agent.reconcile_bluetooth({'mode': 'restart; reboot'})
            assert False
        except RuntimeError:
            pass
        assert not calls

    async def missing(*args):
        assert args[0] == 'show'
        return False, 'LoadState=not-found', ''
    with patch.object(agent, 'bluetooth_command', missing):
        assert not (await agent.reconcile_bluetooth({'mode': 'on'}))['bluetooth_installed']

    async def duplicate(*args):
        assert args[0] == 'show'
        return True, 'LoadState=loaded\nActiveState=active', ''
    with patch.object(agent, 'bluetooth_command', duplicate):
        try:
            await agent.reconcile_bluetooth({'mode': 'off'})
            assert False
        except RuntimeError as error:
            assert 'Multiple' in str(error)

    class Hung:
        returncode = None
        killed = False
        async def communicate(self):
            if self.killed:
                return b'', b''
            raise asyncio.TimeoutError()
        def kill(self):
            self.killed = True
            self.returncode = -9
    hung = Hung()
    async def spawn(*args, **kwargs):
        return hung
    with patch.object(agent.asyncio, 'create_subprocess_exec', spawn):
        assert not (await agent.bluetooth_command('show', unit))[0]
        assert hung.killed, 'timed out processes must be killed and reaped'


with tempfile.TemporaryDirectory() as scratch:
    folder = Path(scratch)
    os.environ.update(PANEL_DIR=str(folder/'panel'), PANEL_DB=str(folder/'panels.db'), ADMIN_PASSWORD='test-only-password')
    (folder/'panel').mkdir()
    spec = importlib.util.spec_from_file_location('bluetooth_agent', ROOT/'agent/panel-agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    asyncio.run(exercise(agent))
    print('PASS scanner: observe, enable, disable, boot, idempotence, failed/missing/conflicting services and subprocess cleanup')
    sys.path.insert(0, str(ROOT/'server'))
    from app.main import app
    with TestClient(app) as client:
        assert client.patch('/api/panels/test/bluetooth', json={'mode':'off'}).status_code == 401
        client.post('/api/login', json={'password':'test-only-password'})
        client.post('/api/register', json={'panel_id':'test','hostname':'test','kind':'pi'})
        client.post('/api/panels/test/claim', json={'room':'Study','template':'default'})
        original = {'lights':[{'entity_id':'light.test','soft':17}], 'media':{'default_speaker':'media_player.test'}, 'display':{'idle_timeout_s':45}}
        assert client.put('/api/panels/test/config', json=original).status_code == 200
        assert client.get('/api/panels/test').json()['config']['bluetooth'] == {'mode':'existing'}
        for mode in ('on','off','existing'):
            assert client.patch('/api/panels/test/bluetooth', json={'mode':mode}).status_code == 200
            cfg = client.get('/api/panels/test').json()['config']
            assert cfg['bluetooth']['mode'] == mode
            assert cfg['lights'] == original['lights'] and cfg['media']['default_speaker']=='media_player.test'
        for bad in ([], None, {'mode':False}, {'mode':'restart'}, {'unit':'ssh.service'}, {'mode':['on']}):
            assert client.patch('/api/panels/test/bluetooth', json=bad).status_code == 400
            assert client.put('/api/panels/test/config', json={**original,'bluetooth':bad}).status_code == 400
            assert client.post('/api/panels/test/config/import', json={**original,'bluetooth':bad}).status_code == 400
        exported = client.get('/api/panels/test/config/export').json()
        assert exported['config']['bluetooth']['mode'] == 'existing'
        assert client.post('/api/panels/test/config/import', json=exported).status_code == 200
        client.post('/api/heartbeat', json={'panel_id':'test','metrics':{'bluetooth_active':True,'bluetooth_memory_mb':32.5,'bluetooth_status':'Running'}})
        assert client.get('/api/panels/test').json()['panel']['metrics']['bluetooth_memory_mb']==32.5
        client.post('/api/register', json={'panel_id':'esp','hostname':'esp','kind':'esp'})
        assert client.patch('/api/panels/esp/bluetooth', json={'mode':'on'}).status_code == 400
    print('PASS server: authentication, defaults, narrow writes, malformed input, export/import and heartbeat persistence')
