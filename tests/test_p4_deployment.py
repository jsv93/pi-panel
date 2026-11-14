"""Exercise update isolation, exact signatures, replay identity and build safety."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import httpx


async def check(server, db, deploy):
    pid='p4-test'; token='t'*40; signing='s'*40
    db.upsert_panel(pid,pid,'aa:bb:cc:dd:ee:ff','192.0.2.1','esp','test')
    db.claim_panel_token(pid,token,signing,'test'); db.claim(pid,'study','default','Study')
    cfg=db.merged_config(pid);cfg['display']['theme']='architectural';db.save_config(pid,cfg)
    server.SESSIONS['test-session']=time.time()+60
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://localhost') as client:
        route=f'/api/panels/{pid}/p4'; auth={'X-Panel-Token':token}
        assert (await client.get(route)).status_code==401
        assert (await client.post(route,json={})).status_code==401
        client.cookies.set('psid','test-session')
        assert (await client.post(route,json={})).status_code==400
        response=await client.post(route,json={'api_name':pid,'api_key':base64.b64encode(bytes(32)).decode()})
        assert response.status_code==200,response.text
        assert 'api_key' not in response.text and signing not in response.text
        job=deploy.status(pid)['jobs'][0]; generation=job['id']
        deploy.queue(pid);assert len(deploy.status(pid)['jobs'])==1
        dynamic=json.loads(json.dumps(cfg));dynamic['display']['palette']='ember'
        assert deploy.shape(dynamic)==deploy.shape(cfg)
        dynamic['room_label']='Another room';assert deploy.shape(dynamic)!=deploy.shape(cfg)
        directory=deploy.ROOT/str(generation);(directory/'artifacts').mkdir(parents=True)
        items=[]
        for role in ('application','volume','text','palette','navigation','home','overlays'):
            data=('private-'+role).encode();digest=hashlib.sha256(data).hexdigest()
            (directory/'artifacts'/(digest+'.bin')).write_bytes(data)
            items.append(dict(role=role,sha256=digest,bytes=len(data)))
        product=dict(hardware=deploy.HARDWARE,application=items[0],artwork=items[1:])
        deploy.validate_product(product,directory/'artifacts')
        manifest=dict(product,_panel_id=pid,_claimed=True,_version=generation,mac='aa:bb:cc:dd:ee:ff',config_version=2)
        raw=deploy.canonical(manifest);(directory/'manifest.json').write_bytes(raw)
        deploy.set_state(dict(id=generation,panel_id=pid),'ready')
        path=f'/api/p4/{pid}/release'
        assert (await client.get(path)).status_code==401 # admin cookie is not device auth
        assert (await client.get(path.replace(pid,'other'),headers=auth)).status_code==401
        release=await client.get(path,headers=auth);assert release.content==raw
        assert release.headers['X-Panel-Signature']==hmac.new(signing.encode(),raw,hashlib.sha256).hexdigest()
        file=f"/api/p4/{pid}/files/{generation}/{items[0]['sha256']}"
        assert (await client.get(file)).status_code==401
        assert (await client.get(file.replace(pid,'other'),headers=auth)).status_code==401
        encrypted=(await client.get(file,headers=auth)).content
        assert encrypted!=b'private-application'
        assert deploy.artifact_cipher(signing,generation,items[0]['sha256']).update(encrypted)==b'private-application'
        for offset in (1,7,16):
            response=await client.get(file,headers={**auth,'Range':f'bytes={offset}-'})
            assert response.status_code==206
            assert deploy.artifact_cipher(signing,generation,items[0]['sha256'],offset).update(response.content)==b'private-application'[offset:]
        assert (await client.get(file[:-64]+'0'*64,headers=auth)).status_code==404
        assert (await client.get(file.replace(str(generation)+'/','99999/'),headers=auth)).status_code==404
        report=f'/api/p4/{pid}/report'
        assert (await client.post(report,headers=auth,json={'generation':generation,'state':'installed'})).is_success
        assert deploy.status(pid)['jobs'][0]['state']=='installed'
        assert (await client.post(report,headers=auth,json={'generation':999999,'state':'installed'})).status_code==404
        db.save_config(pid,dynamic)
        assert (await client.get(path,headers=auth)).status_code==204 # obsolete room cannot install
        deploy.queue(pid);assert len(deploy.status(pid)['jobs'])==2
        new=deploy.status(pid)['jobs'][0];deploy.set_state(dict(id=new['id'],panel_id=pid),'building')
        deploy.init();assert deploy.status(pid)['jobs'][0]['state']=='queued'
        # A changed room must terminate obsolete compiler work promptly. This
        # exercises a real child process, without compiling or touching devices.
        process=await asyncio.create_subprocess_exec(sys.executable,'-c','import time; time.sleep(120)',start_new_session=os.name!='nt')
        try:
            obsolete=dict(panel_id=pid,shape='obsolete-shape')
            assert await deploy.wait_build(process,obsolete,interval=.05) is None
            assert process.returncode is not None
        finally:await deploy.stop_build(process)
        asset=directory/'artifacts'/(items[1]['sha256']+'.bin');asset.write_bytes(b'corrupt')
        try:deploy.validate_product(product,directory/'artifacts');raise AssertionError('accepted corruption')
        except ValueError:pass
        # Disk retention is scoped to this panel's owned jobs. Keep both
        # rollback releases while removing disposable compiler/render output.
        unrelated=deploy.ROOT/'unrelated.txt';unrelated.write_text('keep')
        with db.conn() as c:
            for offset in (2,3):
                number=generation+offset
                c.execute("INSERT INTO p4_builds(id,panel_id,shape,version,state,created) VALUES(?,?,?,1,'installed',?)",(number,pid,'test',time.time()))
                folder=deploy.ROOT/str(number)
                (folder/'artifacts').mkdir(parents=True);(folder/'artifacts/keep.bin').write_bytes(b'keep')
                (folder/'build').mkdir();(folder/'build/disposable').write_text('compiler output')
        deploy.trim_storage(pid)
        assert unrelated.read_text()=='keep' and not (directory/'artifacts').exists()
        for offset in (2,3):
            folder=deploy.ROOT/str(generation+offset)
            assert (folder/'artifacts/keep.bin').read_bytes()==b'keep' and not (folder/'build').exists()
    print('PASS device/admin isolation, signed release, scoped artifacts, corruption rejection, superseded config, durable queue')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as directory:
        os.environ['PANEL_DB']=str(Path(directory)/'panel.db')
        os.environ['PANEL_P4_DATA']=str(Path(directory)/'p4')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
        from app import main,db,p4_deployment
        asyncio.run(check(main,db,p4_deployment))
