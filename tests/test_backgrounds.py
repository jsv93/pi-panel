"""Admin-only background writes, bounded image conversion and offline caching."""
import asyncio
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as scratch:
    os.environ['PANEL_DB'] = str(Path(scratch) / 'panels.db')
    os.environ['PANEL_DIR'] = str(Path(scratch) / 'panel')
    Path(os.environ['PANEL_DIR']).mkdir()
    os.environ['ADMIN_PASSWORD'] = 'test-only'
    sys.path.insert(0, str(ROOT / 'server'))
    from app.main import app
    from app import backgrounds
    with TestClient(app) as client:
        picture = io.BytesIO()
        Image.new('RGB', (1800, 2400), '#60442d').save(picture, 'JPEG')
        raw = picture.getvalue()
        assert client.post('/api/backgrounds', content=raw).status_code == 401
        assert client.post('/api/login', json={'password':'test-only'}).status_code == 200
        for panel in ['study', 'other']:
            assert client.post('/api/register', json={'panel_id':panel,'hostname':panel}).status_code == 200
        original = {'room_label':'Study','lights':[{'entity_id':'light.one','soft':31}], 'display':{'theme':'architectural','palette':'linen'}}
        assert client.put('/api/panels/study/config', json=original).status_code == 200
        result = client.post('/api/backgrounds', content=raw)
        assert result.status_code == 200, result.text
        info = result.json(); digest=info['image']
        assert (info['width'],info['height']) == (960,1280)
        served = client.get('/api/backgrounds/'+digest)
        assert served.headers['content-type'] == 'image/webp'
        asset = served.content
        assert hashlib.sha256(asset).hexdigest() == digest
        with Image.open(io.BytesIO(asset)) as image:
            assert image.format == 'WEBP' and 'exif' not in image.info
        assert client.post('/api/backgrounds', content=b'<svg/>').status_code == 400
        assert client.post('/api/backgrounds', content=b'x'*(backgrounds.MAX_UPLOAD+1)).status_code == 413
        chosen={'mode':'image','colour':'#2b2018','image':digest}
        assert client.patch('/api/panels/study/background',json=chosen).status_code == 200
        cfg=client.get('/api/panels/study').json()['config']
        assert cfg['lights']==original['lights'] and cfg['display']['theme']=='architectural'
        assert client.get('/api/background/study/'+digest).content == asset
        assert client.get('/api/background/other/'+digest).status_code == 404
        assert client.patch('/api/panels/study/display',json={'background':chosen}).status_code == 400
        for invalid in [{'mode':'url','colour':'#abcdef'}, {'mode':'solid','colour':'red;url(x)'}, {'mode':'image','image':'../secret'}, {'mode':'image','image':'0'*64}]:
            assert client.patch('/api/panels/study/background',json=invalid).status_code == 400
            assert client.put('/api/panels/study/config',json={'display':{'background':invalid}}).status_code == 400
        for mode in ['solid','room','pattern']:
            assert client.patch('/api/panels/study/background',json={'mode':mode,'colour':'#302218'}).status_code == 200
        outer=FastAPI();outer.mount('/api/hassio_ingress/testtoken',app)
        with TestClient(outer) as ingress:
            prefix='/api/hassio_ingress/testtoken'
            assert ingress.post(prefix+'/api/login',json={'password':'test-only'}).status_code == 200
            assert ingress.post(prefix+'/api/backgrounds',content=raw).json()['image']==digest
            assert ingress.get(prefix+'/api/backgrounds/'+digest).content==asset
            assert ingress.get(prefix+'/abstract-room.webp').status_code==200
        print('PASS image validation, sizing, auth, config preservation, ingress and all four styles')

    spec=importlib.util.spec_from_file_location('background_agent',ROOT/'agent/panel-agent.py')
    agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    class Response:
        status=200
        def __init__(self,data): self.data=data;self.content=self
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def iter_chunked(self,size):
            for at in range(0,len(self.data),size): yield self.data[at:at+size]
    class Session:
        def __init__(self,data): self.data=data;self.calls=0
        def get(self,*args,**kwargs): self.calls+=1;return Response(self.data)
    async def check_cache():
        config={'display':{'background':chosen}}
        session=Session(asset)
        assert await agent.cache_background(session,config)
        target=agent.CONFIG_PATH.parent/f'background-{digest}.webp'
        assert target.read_bytes()==asset
        assert not await agent.cache_background(session,config) and session.calls==1
        target.write_bytes(b'old')
        assert not await agent.cache_background(Session(b'corrupt'),config)
        assert target.read_bytes()==b'old'
        assert await agent.cache_background(session,config)
        assert not await agent.cache_background(Session(asset),{'display':{'background':{'mode':'image','image':'../bad'}}})
        async def fetch(_): return {**config,'_claimed':True,'_version':8}
        async def reload(): reload.calls+=1;return 1
        reload.calls=0;agent.fetch_config=fetch;agent.reload_ui=reload;agent.local_version=lambda:8
        target.unlink()
        assert not await agent.sync(session)
        assert reload.calls==1 and target.read_bytes()==asset
    asyncio.run(check_cache())
    print('PASS offline cache, signed-digest integrity, traversal rejection and same-version retry')
