"""Isolated first-install authorization and package tests; no hardware writes."""
import asyncio, base64, hashlib, json, os, sys, tempfile, time
from pathlib import Path
import httpx

async def check(main,db,setup,deploy):
    probe=dict(schema=1,chip='ESP32-P4',revision=103,flash='32MB',mac='02:00:00:00:00:01',installed=False)
    body=dict(room='New study',template='default')
    main.SESSIONS['setup-test']=time.time()+60
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://192.0.2.10:8099') as c:
        assert (await c.post('/api/p4-setup',json=body)).status_code==401
        c.cookies.set('psid','setup-test')
        response=await c.post('/api/p4-setup',json=body)
        assert response.status_code==200,response.text
        pid=response.json()['panel_id'];panel=db.get_panel(pid)
        assert panel['claimed'] and panel['kind']=='esp' and not panel['last_seen'] and not panel['mac']
        assert not deploy.status(pid)['jobs'] and not deploy.status(pid)['enrolled']
        credentials=(db.get_panel_token(pid),db.get_panel_sign_key(pid))
        assert all(len(x)>=40 for x in credentials)
        connect='/api/p4-setup/'+pid+'/connect'
        assert (await c.post(connect,json=probe)).status_code==400 # configure before install
        cfg=db.get_config(pid);cfg['lights']=[dict(entity_id='light.test',name='Test lamp',soft=30,bright=100)]
        db.save_config(pid,cfg)
        for invalid in ({'installed':True},{'chip':'ESP32-C6'},{'revision':300},{'flash':'16MB'},{'mac':'../a'}):
            assert (await c.post(connect,json={**probe,**invalid})).status_code==400
        c.cookies.clear()
        assert (await c.post(connect,json=probe)).status_code==401
        c.cookies.set('psid','setup-test')
        connected=await c.post(connect,json=probe)
        assert connected.status_code==200,connected.text
        assert db.get_panel(pid)['mac']==probe['mac']
        key=await c.get('/api/p4-setup/'+pid+'/pairing')
        assert len(base64.b64decode(key.json()['api_key']))==32 and key.headers['cache-control']=='no-store'
        # A retry uses the same identity and queued/ready build.
        first=deploy.status(pid)['jobs'][0]['id']
        assert (await c.post(connect,json=probe)).status_code==200
        assert len(deploy.status(pid)['jobs'])==1
        assert (await c.get('/api/p4-setup/'+pid+'/pairing')).json()==key.json()
        assert (await c.post(connect,json={**probe,'mac':'02:00:00:00:00:02'})).status_code==409
        second=(await c.post('/api/p4-setup',json=body)).json()['panel_id']
        db.save_config(second,cfg)
        assert (await c.post('/api/p4-setup/'+second+'/connect',json=probe)).status_code==409
        assert credentials==(db.get_panel_token(pid),db.get_panel_sign_key(pid))
        assert 'api_key' not in (await c.get('/api/p4-setup')).text
        generation=first;folder=deploy.ROOT/str(generation);artifact_dir=folder/'artifacts';artifact_dir.mkdir()
        def artifact(role,data,offset=None):
            digest=hashlib.sha256(data).hexdigest();(artifact_dir/(digest+'.bin')).write_bytes(data)
            return dict(role=role,bytes=len(data),sha256=digest,**({'offset':offset} if offset is not None else {}))
        application=artifact('application',b'application')
        artwork=[artifact(role,role.encode()) for role in ('volume','text','palette','navigation','home','overlays')]
        usb=[{**application,'offset':0x10000}]
        for role,(offset,size) in setup.OFFSETS.items():
            if role!='application':usb.append(artifact(role,b'\xff'*size if role in ('nvs','otadata') else role.encode(),offset))
        product=dict(hardware=deploy.HARDWARE,application=application,artwork=artwork,usb=usb)
        (folder/'product.json').write_text(json.dumps(product))
        route=f'/api/p4-setup/{pid}/package/{generation}'
        assert (await c.get(route)).status_code==409
        deploy.set_state(dict(id=generation,panel_id=pid),'ready')
        assert (await c.post(connect,json=probe)).status_code==200
        assert deploy.status(pid)['jobs'][0]['id']==first # no redundant compile
        result=await c.get(route);assert result.status_code==200,result.text
        assert result.json()['mac']==probe['mac'] and 'no-store' in result.headers['cache-control']
        assert (await c.get(route.replace(pid,second))).status_code==409
        c.cookies.clear()
        assert (await c.get(route,headers={'X-Panel-Token':credentials[0]})).status_code==401
        c.cookies.set('psid','setup-test')
        path=artifact_dir/(usb[1]['sha256']+'.bin');original=path.read_bytes();path.write_bytes(b'bad')
        assert (await c.get(route)).status_code==409
        path.write_bytes(original)
        deploy.set_state(dict(id=generation,panel_id=pid),'installed')
        assert not setup.initial_install(pid)
        assert (await c.get(route)).status_code==409
        assert (await c.post(connect,json=probe)).status_code==409
        assert (await c.delete('/api/panels/'+second)).status_code==200
        with db.conn() as conn:assert not conn.execute('SELECT 1 FROM p4_setup WHERE panel_id=?',(second,)).fetchone()
    print('PASS provisional P4, authenticated USB binding, protected identities, retry reuse, private package and installed-device lockout')

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['PANEL_DB']=str(Path(tmp)/'db.sqlite');os.environ['PANEL_P4_DATA']=str(Path(tmp)/'p4')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
        from app import main,db,p4_setup,p4_deployment
        asyncio.run(check(main,db,p4_setup,p4_deployment))
