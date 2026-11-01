"""Kernel counter math, bounded telemetry, and authenticated key-management transport."""
import asyncio
import base64
import concurrent.futures
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    os.environ.update(PANEL_DIR=str(tmp), PANEL_DB=str(tmp/'server.db'), ADMIN_PASSWORD='test-only-password')
    spec = importlib.util.spec_from_file_location('new_agent', ROOT/'agent/panel-agent.py')
    ag = importlib.util.module_from_spec(spec); spec.loader.exec_module(ag)
    proc = tmp/'proc'; (proc/'net').mkdir(parents=True)
    ag.MEMINFO = proc/'meminfo'
    ag.MEMINFO.write_text('MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n')
    (proc/'loadavg').write_text('0.45 0.3 0.2 1/100 12')
    (proc/'net/route').write_text('Iface Destination Gateway Flags\neth0 00000000 00000000 0003\n')
    def counters(user, idle, rx, tx):
        (proc/'stat').write_text(f'cpu {user} 0 0 {idle} 0 0 0 0 9999 0\n')
        (proc/'net/dev').write_text(f'header\nheader\neth0: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n')
    sampler=ag.PerformanceSampler(proc)
    with patch.object(ag,'_root_device',return_value='mmcblk0'),patch.object(ag,'_sectors_written',side_effect=[100,120,1]):
        counters(100,900,1000,2000); first=sampler.sample(10)
        assert 'cpu_usage_pct' not in first and 'net_rx_kbps' not in first
        counters(125,975,11000,7000); second=sampler.sample(15)
        assert second['cpu_usage_pct']==25 and second['net_rx_kbps']==2 and second['net_tx_kbps']==1
        assert second['disk_write_kbps']==2.05 and second['ram_used_pct']==50
        counters(1,1,0,0); reset=sampler.sample(20)
        assert not {'cpu_usage_pct','net_rx_kbps','disk_write_kbps'} & reset.keys()
    print('PASS five-second deltas, first sample, guest-time exclusion, counter reset, RAM and disk units')

    sys.path.insert(0,str(ROOT/'server'))
    from app import main, db, performance, access
    key=ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
    assert access.validate({'action':'add','user':'joel','key':key+' comment','name':'Laptop'})['key']==key
    for bad in ['-----BEGIN OPENSSH PRIVATE KEY-----','command="sh" '+key,key+'\n'+key,'ssh-ed25519 AAAA']:
        try: access.validate({'action':'add','key':bad,'name':'Laptop'})
        except ValueError: pass
        else: raise AssertionError('invalid key accepted')
    token='t'*40; sign='s'*40; auth={'X-Panel-Token':token}
    with TestClient(main.app) as c:
        for pid in ['p1','p2']:
            c.post('/api/register',json={'panel_id':pid,'hostname':pid})
        db.claim_panel_token('p1',token,sign,'test')
        db.claim_panel_token('p2','u'*40,'v'*40,'test')
        assert c.post('/api/performance/p1',json={'cpu_usage_pct':10}).status_code==401
        assert c.post('/api/performance/p2',headers=auth,json={'cpu_usage_pct':10}).status_code==401
        assert c.get('/api/panels/p1/performance').status_code==401
        assert c.post('/api/login',json={'password':'test-only-password'}).status_code==200
        assert c.get('/api/panels/p1/performance?period=bogus').status_code==400
        with patch.object(performance.time,'time',return_value=200000):
            assert c.post('/api/performance/p1',headers=auth,json={'cpu_usage_pct':0,'ram_used_pct':51,'load_1m':True,'cpu_temp':'55','unknown':2}).status_code==200
            c.post('/api/performance/p1',headers=auth,json={'cpu_usage_pct':90})
            result=c.get('/api/panels/p1/performance').json()
            assert len(result['samples'])==1 and result['samples'][0]['cpu_usage_pct']==0
            assert 'load_1m' not in result['samples'][0] and 'cpu_temp' not in result['samples'][0]
            assert not c.get('/api/panels/p2/performance').json()['samples']
        with patch.object(performance.time,'time',return_value=200005):
            c.post('/api/performance/p1',headers=auth,json={'cpu_usage_pct':100})
            assert len(c.get('/api/panels/p1/performance').json()['samples'])==2
            assert c.get('/api/panels/p1/performance?period=24h').json()['samples'][0]['cpu_usage_pct']==50
        with patch.object(performance.time,'time',return_value=300000):
            performance.record('p1',{'cpu_usage_pct':30})
            with db.conn() as sql: assert sql.execute('SELECT COUNT(*) FROM performance').fetchone()[0]==1
        print('PASS device-token isolation, admin-only history, zero/missing values, rate cap, aggregation and retention')

        assert c.post('/api/panels/p1/ssh-access',json={'action':'list'}).status_code==403
        headers={'X-Panel-Access':'1'}
        assert c.post('/api/panels/p1/ssh-access',headers=headers,json={'action':'shell'}).status_code==400
        assert c.post('/api/panels/p1/ssh-access',headers=headers,json={'action':'list'}).status_code==503
        with c.websocket_connect('/api/ws/p1',headers=auth) as ws:
            ws.receive_json()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                call=pool.submit(c.post,'/api/panels/p1/ssh-access',headers=headers,json={'action':'add','user':'joel','key':key,'name':'Test laptop'})
                sent=ws.receive_json()
                assert sent['panel_id']=='p1' and sent['action']=='add' and sent['user']=='joel'
                signature=sent.pop('_sig')
                assert hmac.compare_digest(signature,hmac.new(sign.encode(),main.canonical(sent),hashlib.sha256).hexdigest())
                response={'type':'ssh_access_result','request_id':sent['request_id'],'user':'joel','users':['joel'],'keys':[],'changed':True}
                ws.send_json(main.signed('p1',response))
                received=call.result(timeout=5)
                assert received.status_code==200,received.text
                assert [a['action'] for a in received.json()['audit']]==['add completed','add requested']
                assert '_sig' not in received.json()
        print('PASS access schema, CSRF header, offline handling, device-signed request/reply and durable audit')

    # Agent request validation is independent of Linux account inspection.
    with patch.dict(sys.modules,{'pwd':type('Pwd',(),{'getpwall':lambda:[]})}):
        ag.SIGN_KEY=sign; ag.PANEL_ID='p1'; ag.ACCESS_SEEN.clear()
        assert 'error' in ag.ssh_access({'panel_id':'p2'})
        assert 'expired' in ag.ssh_access({'panel_id':'p1','expires':0,'request_id':'old'})['error']
    print('PASS cross-device and expired access requests are rejected')
