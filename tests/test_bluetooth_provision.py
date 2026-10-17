"""Exercise the actual installer, generated bootstrap and HA discovery logic.

OS package/systemd commands and HA boundaries are simulated; files, archive,
patching, config database and event handling are real. No hardware is changed.
"""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def installer_test(folder):
    installer = module('installer', ROOT/'pi-os/install-bluetooth.py')
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('systemctl', 'show'):
            return 'not-found'
        if args == ('bluetoothctl', 'show'):
            return 'Controller AA:BB:CC:DD:EE:11 (public)\nPowered: yes'
        return ''
    archive = ROOT/'pi-os/vendor/bt-proxy-3929ecb.tar.gz'
    adapter = folder/'hci0'
    adapter.mkdir()
    with patch.multiple(installer, ROOT=folder/'proxy', PANEL=folder/'panel',
                        UNIT=folder/'panel-bt-proxy.service', ADAPTER=adapter), \
         patch.object(installer, 'run', run), \
         patch.object(installer.socket, 'getaddrinfo', return_value=[(2,1,6,'',('192.168.1.11',6053))]):
        installer.install(archive, 'http://ha.local:8123', 'living-1234', 'on')
        marker = json.loads((folder/'panel/bluetooth-provision.json').read_text())
        assert marker['managed'] and marker['panel_id'] == 'living-1234'
        assert ('systemctl','enable','--now','panel-bt-proxy.service') in calls
        text = (folder/'proxy/bt_proxy/api_server.py').read_text()
        assert 'FEATURE_ACTIVE_CONNECTIONS' not in text
        assert 'FEATURE_REMOTE_CACHING' not in text
        compile(text, 'patched api_server.py', 'exec')
        assert "getaddrinfo('ha.local', 6053" in text
        assert 'peer[0] not in allowed' in text
        assert '--max-connections 0' in (folder/'panel-bt-proxy.service').read_text()
        # Reinstalling Study must not install packages, rewrite identities or
        # even change an existing service's enabled/disabled state.
        calls.clear()
        with patch.object(installer, 'existing_service', return_value='study-bt-proxy.service'):
            installer.install(archive, 'http://invalid.local', 'new-name', 'on')
        assert not calls
        assert json.loads((folder/'panel/bluetooth-provision.json').read_text()) == marker
        # A disabled template still gets the software, without starting it.
        installer.install(archive, 'http://ha.local:8123', 'living-1234', 'off')
        assert not any(c[:3] == ('systemctl','enable','--now') and c[-1] == 'panel-bt-proxy.service' for c in calls)
        for url in ('http://localhost:8123','http://user:secret@ha.local','http://ha.local;touch'):
            try:
                installer.ha_host(url)
                raise AssertionError('unsafe host accepted')
            except ValueError:
                pass
        bad = folder/'bad.tar.gz'
        bad.write_bytes(b'wrong')
        calls.clear()
        try:
            installer.install(bad, 'http://ha.local:8123', 'new', 'on')
            raise AssertionError('unchecked source installed')
        except ValueError:
            pass
        assert not any(c[0] == 'apt-get' for c in calls)
        with patch.object(installer, 'ADAPTER', folder/'missing'):
            try:
                installer.install(archive, 'http://ha.local:8123', 'new', 'on')
                raise AssertionError('missing adapter ignored')
            except ValueError:
                pass
    print('PASS installer: pinned source, scan-only patch, boot startup, disabled mode, legacy preservation, invalid host/archive/hardware')


def server_test(folder):
    os.environ.update(PANEL_DB=str(folder/'panels.db'), ADMIN_PASSWORD='test-only')
    sys.path.insert(0, str(ROOT/'server'))
    from app import main, db
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    client.post('/api/login', json={'password':'test-only'})
    pid = db.create_provisional_panel('Living', 'default')
    assert db.merged_config(pid)['bluetooth']['mode'] == 'on'
    assert db.DEFAULT_TEMPLATE['bluetooth']['mode'] == 'existing'
    token = db.create_token(pid)
    response = client.get('/bootstrap.sh', params={'t':token})
    assert response.status_code == 200
    assert '__BLUETOOTH_' not in response.text
    assert '--mode on' in response.text and 'install-bluetooth.py' in response.text
    assert 'Panel setup continues' in response.text
    assert client.get('/bootstrap.sh', params={'t':token}).status_code == 404
    (folder/'bootstrap.sh').write_text(response.text)
    print('PASS provisioning API: new default enabled, migration default unchanged, script wiring, one-use token')


async def discovery_test():
    # Minimal HA boundaries; exercise production discovery callbacks/flows.
    modules = {name:ModuleType(name) for name in (
        'homeassistant','homeassistant.config_entries','homeassistant.helpers',
        'homeassistant.helpers.area_registry','homeassistant.helpers.device_registry')}
    modules['homeassistant.config_entries'].SOURCE_USER='user'
    modules['homeassistant.config_entries'].SOURCE_IGNORE='ignore'
    areas = modules['homeassistant.helpers.area_registry']
    devices = modules['homeassistant.helpers.device_registry']
    with patch.dict(sys.modules, modules):
        discovery = module('discovery', ROOT/'custom_components/pi_panel/discovery.py')
    listeners=[]
    unload=[]
    def listen(callback):
        listeners.append(callback)
        return lambda:listeners.remove(callback)
    coordinator=NS(data={'study':{}}, async_add_listener=listen)
    entry=NS(runtime_data=coordinator, async_on_unload=unload.append)
    added=[]
    discovery.watch_panels(entry, added.extend, lambda pid:[pid+'_light',pid+'_screen'])
    coordinator.data['new']={}
    listeners[0](); listeners[0]()
    assert added==['study_light','study_screen','new_light','new_screen']
    coordinator.data.pop('new'); listeners[0]()
    coordinator.data['new']={}; listeners[0]()
    assert len(added)==4
    unload[0](); assert not listeners

    panel={'id':'new','claimed':True,'kind':'pi','online':True,'ip':'192.168.1.222','room':'Living',
           'metrics':{'bluetooth_managed':True,'bluetooth_active':True,'bluetooth_mac':'AA:BB:CC:DD:EE:11','bluetooth_sample_at':time.time()}}
    for key,value in [('bluetooth_managed',False),('bluetooth_active',False),('bluetooth_mac','00:00:00:00:00:00'),('bluetooth_sample_at',0)]:
        bad=copy.deepcopy(panel); bad['metrics'][key]=value
        assert discovery.scanner_candidate(bad) is None
    bad=copy.deepcopy(panel); bad['ip']='8.8.8.8'
    assert discovery.scanner_candidate(bad) is None

    entries=[]; updates=[]; flows=[]; calls=[]; outcome='success'
    async def init(domain,context):
        calls.append(('init',domain,context)); flows.append({'flow_id':'test'})
        return {'type':'form','step_id':'user','flow_id':'test'}
    async def configure(fid,user_input):
        calls.append(('configure',fid,user_input))
        if outcome == 'offline':
            return {'type':'form','step_id':'user','flow_id':'test','errors':{'base':'cannot_connect'}}
        if outcome == 'cancel':
            raise asyncio.CancelledError()
        result=NS(entry_id='new-entry',unique_id='aa:bb:cc:dd:ee:11',source='user',options={})
        entries.append(result); flows.clear()
        return {'type':'create_entry','result':result}
    def update(entry,options):
        entry.options=options; updates.append(options)
    def abort(fid):
        flows.clear()
    hass=NS(config_entries=NS(async_entries=lambda domain:entries,
        async_update_entry=update, flow=NS(async_init=init,async_configure=configure,
        async_progress=lambda:flows,async_abort=abort)))
    enrollment=discovery.ScannerEnrollment(hass,coordinator)
    await enrollment.enroll(panel)
    assert updates[0]['bluetooth_scanning_mode']=='active'
    assert updates[0]['allow_service_calls'] is False
    assert calls[1][2]=={'host':'192.168.1.222','port':6053}
    assigned=[]
    areas.async_get=lambda h:NS(async_list_areas=lambda:[NS(id='living',name='Living')])
    devices.async_get=lambda h:NS(async_update_device=lambda id,**kw:assigned.append((id,kw)))
    devices.async_entries_for_config_entry=lambda r,id:[NS(id='scanner',area_id=None)]
    enrollment.retry_at.clear()
    await enrollment.enroll(panel)
    assert assigned==[('scanner',{'area_id':'living'})]
    await enrollment.enroll(panel)
    assert len(calls)==2
    # Legacy/ignored entries retain all their settings and area.
    entries[0].source='ignore'; updates.clear()
    await discovery.ScannerEnrollment(hass,coordinator).enroll(panel)
    assert not updates and len(calls)==2
    entries.clear(); outcome='offline'
    enrollment=discovery.ScannerEnrollment(hass,coordinator)
    await enrollment.enroll(panel); before=len(calls)
    await enrollment.enroll(panel)
    assert not flows and len(calls)==before
    outcome='cancel'; enrollment.retry_at.clear()
    try:
        await enrollment.enroll(panel)
    except asyncio.CancelledError:
        pass
    assert not flows
    print('PASS HA: dynamic entities, unload cleanup, eligibility, enroll, active scanning, area match, dedup, ignored entries, outage backoff, canceled flow cleanup')


with tempfile.TemporaryDirectory() as scratch:
    folder=Path(scratch)
    installer_test(folder)
    server_test(folder)
    asyncio.run(discovery_test())
