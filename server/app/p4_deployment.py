"""Private, durable per-device builds. The serving process never runs a compiler.

Only enrolled P4s participate. Old applications and their immutable artwork stay
available for rollback; a failed or obsolete build never replaces a release.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import shutil
import sys
import time

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from . import access, backgrounds, db, ha

ROOT = Path(os.environ.get('PANEL_P4_DATA', str(Path(db.DB_PATH).parent/'p4')))
SOURCE = Path(os.environ.get('PANEL_P4_SOURCE', str(Path(__file__).resolve().parents[2])))
HARDWARE = 'waveshare-p4-wifi6-32mb-5dsi-720x1280-v1'
ENCRYPTION = 'aes-256-ctr-signed-sha256-v1'
HEX = re.compile(r'[0-9a-f]{64}')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def artifact_cipher(signing_key, generation, digest, offset=0):
    # A fresh key per device/generation/content makes the all-zero initial CTR
    # unique per plaintext. Retries encrypt the same bytes with the same key.
    # The separately HMAC-signed manifest authenticates the complete SHA-256;
    # the P4 never opens or executes a file before that verification succeeds.
    context=f'p4-artifact-v1\n{generation}\n{digest}'.encode()
    key=hmac.new(signing_key.encode(),context,hashlib.sha256).digest()
    cipher=Cipher(algorithms.AES(key),modes.CTR((offset//16).to_bytes(16,'big'))).encryptor()
    cipher.update(bytes(offset%16))
    return cipher


def shape(config):
    value = json.loads(json.dumps(config))
    for key in list(value):
        if key.startswith('_'): value.pop(key)
    for light in value.get('lights', []):
        for key in ('soft', 'bright', 'include_presets'): light.pop(key, None)
    # These choices already use the small, signed live-config protocol.
    for key in ('palette', 'diagnostics', 'browse_view', 'mini_art'):
        value.get('display', {}).pop(key, None)
    return hashlib.sha256(canonical(value)).hexdigest()


def init():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with db.conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS p4_devices (
          panel_id TEXT PRIMARY KEY, api_key TEXT NOT NULL, api_name TEXT NOT NULL,
          server TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS p4_builds (
          id INTEGER PRIMARY KEY AUTOINCREMENT, panel_id TEXT NOT NULL,
          shape TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
          created REAL NOT NULL, detail TEXT NOT NULL DEFAULT '', report TEXT NOT NULL DEFAULT '{}');
        ''')
        # A compiler killed by a server restart is safe to restart in its job directory.
        c.execute("UPDATE p4_builds SET state='queued', detail='Resuming after server restart' WHERE state='building'")


def status(panel_id):
    with db.conn() as c:
        enrolled = c.execute('SELECT enabled FROM p4_devices WHERE panel_id=?', (panel_id,)).fetchone()
        rows = c.execute('SELECT id,version,state,created,detail,report FROM p4_builds WHERE panel_id=? ORDER BY id DESC LIMIT 8', (panel_id,)).fetchall()
    jobs = [dict(row) for row in rows]
    for job in jobs:
        if job['state'] == 'building':
            try: job['detail'] = json.loads((ROOT/str(job['id'])/'progress.json').read_bytes())['phase']
            except (OSError, ValueError, KeyError): pass
        job['report'] = json.loads(job['report'])
    return dict(enrolled=bool(enrolled), enabled=bool(enrolled and enrolled['enabled']), jobs=jobs)


def queue(panel_id, retry=False):
    cfg = db.merged_config(panel_id)
    fingerprint = shape(cfg)
    with db.conn() as c:
        device = c.execute('SELECT * FROM p4_devices WHERE panel_id=? AND enabled=1', (panel_id,)).fetchone()
        if not device: return
        last = c.execute('SELECT * FROM p4_builds WHERE panel_id=? ORDER BY id DESC LIMIT 1', (panel_id,)).fetchone()
        if last and last['shape'] == fingerprint and not retry: return
        if last and last['state'] in ('queued', 'building') and retry: return
        # Time-based floor also survives restoring an older database backup.
        # Seconds since 2020 fit the embedded signed 32-bit generation field.
        generation=max(int(time.time())-1577836800, c.execute('SELECT COALESCE(MAX(id),0)+1 FROM p4_builds').fetchone()[0])
        c.execute("INSERT INTO p4_builds(id,panel_id,shape,version,state,created) VALUES(?,?,?,?,'queued',?)",
                  (generation, panel_id, fingerprint, db.latest_version(panel_id), time.time()))


def build_log(panel_id, generation):
    with db.conn() as c:
        job=c.execute('SELECT id FROM p4_builds WHERE id=? AND panel_id=?',(generation,panel_id)).fetchone()
        device=c.execute('SELECT api_key FROM p4_devices WHERE panel_id=?',(panel_id,)).fetchone()
    if not job:raise HTTPException(404,'Unknown build for this panel')
    path=ROOT/str(generation)/'build.log'
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):raise HTTPException(404)
    try:
        with path.open('rb') as f:
            f.seek(0,2);size=f.tell();f.seek(max(0,size-65536));raw=f.read(65536)
    except FileNotFoundError:return dict(text='Build log is not available yet.',truncated=False)
    text=raw.decode('utf8','replace')
    for secret in (device['api_key'] if device else '',db.get_panel_token(panel_id),
                   db.get_panel_sign_key(panel_id),ha.token(),os.environ.get('ADMIN_PASSWORD','')):
        if secret:text=text.replace(secret,'[redacted]')
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    return dict(text=text,truncated=size>len(raw))


def set_state(job, state, detail=''):
    with db.conn() as c:
        c.execute('UPDATE p4_builds SET state=?,detail=? WHERE id=?', (state, detail[:200], job['id']))
    access.audit(job['panel_id'], 'p4-builder', state, f"Build {job['id']}: {detail[:140]}")


def validate_product(product, directory):
    if product.get('hardware') != HARDWARE: raise ValueError('Wrong hardware product')
    items = [product['application'], *product['artwork']]
    if len(items) != 7 or {item['role'] for item in items} != {'application','volume','text','palette','navigation','home','overlays'}:
        raise ValueError('Incomplete artwork product')
    for item in items:
        digest, size = item['sha256'], item['bytes']
        if not HEX.fullmatch(digest) or type(size) is not int or not 0 < size <= 160*1024*1024:
            raise ValueError('Invalid artifact identity')
        if item['role'] == 'application' and size > 0x300000: raise ValueError('Application exceeds partition')
        path = directory/(digest+'.bin')
        with path.open('rb') as f:
            if path.stat().st_size != size or hashlib.file_digest(f, 'sha256').hexdigest() != digest:
                raise ValueError('Artifact verification failed')


def trim_storage(panel_id):
    """Keep two installed releases and two offers; discard only owned job data."""
    with db.conn() as c:
        rows=c.execute('SELECT id,state FROM p4_builds WHERE panel_id=? ORDER BY id DESC',(panel_id,)).fetchall()
        keep=set()
        for state in ('installed','ready'):
            keep.update(row['id'] for row in [r for r in rows if r['state']==state][:2])
        for row in rows:
            if row['state'] in ('ready','installed') and row['id'] not in keep:
                c.execute("UPDATE p4_builds SET state='retired', detail='Newer releases retained for rollback' WHERE id=?",(row['id'],))
    root=ROOT.resolve()
    for row in rows:
        if row['state'] in ('queued','building'):continue
        directory=ROOT/str(row['id'])
        if directory.is_symlink() or directory.resolve().parent!=root:continue
        names=['palettes','overlays','palette-source.bin','build','overlay-assets','navigation-assets','home-assets','private-assets']
        if row['id'] not in keep:names.append('artifacts')
        for name in names:
            path=directory/name
            if path.is_symlink() or not path.resolve().is_relative_to(root):continue
            if path.is_dir():shutil.rmtree(path)
            elif path.is_file():path.unlink()


async def existing_api_name(panel,key):
    from aioesphomeapi import APIClient
    client=APIClient(panel['ip'],6053,'',noise_psk=key)
    try:
        await asyncio.wait_for(client.connect(login=True),15)
        info=await client.device_info()
        if info.mac_address.lower()!=panel['mac'].lower():raise ValueError('Different device')
        return info.name
    except Exception as error:
        raise HTTPException(400,'Connect the P4 and check its existing Home Assistant pairing key; its device identity must be preserved') from error
    finally:await client.disconnect()


async def stop_build(process):
    if process.returncode is not None:return
    try:
        if os.name!='nt':os.killpg(process.pid,signal.SIGTERM)
        else:process.terminate()
    except ProcessLookupError:return
    try:await asyncio.wait_for(process.wait(),10)
    except asyncio.TimeoutError:
        if os.name!='nt':os.killpg(process.pid,signal.SIGKILL)
        else:process.kill()
        await process.wait()


async def wait_build(process,job,interval=15):
    deadline=time.monotonic()+4*60*60
    try:
        while time.monotonic()<deadline:
            try:return await asyncio.wait_for(process.wait(),interval)
            except asyncio.TimeoutError:pass
            with db.conn() as c:
                device=c.execute('SELECT enabled FROM p4_devices WHERE panel_id=?',(job['panel_id'],)).fetchone()
            if not device or not device['enabled'] or shape(db.merged_config(job['panel_id']))!=job['shape']:
                await stop_build(process);return None
        raise asyncio.TimeoutError()
    except (asyncio.TimeoutError,asyncio.CancelledError):
        await stop_build(process);raise


async def worker():
    while True:
        try:
            with db.conn() as c:
                devices = c.execute('SELECT panel_id FROM p4_devices WHERE enabled=1').fetchall()
            for device in devices: queue(device['panel_id'])
            with db.conn() as c:
                row = c.execute("SELECT * FROM p4_builds WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                await asyncio.sleep(15); continue
            job = dict(row); pid = job['panel_id']; directory = ROOT/str(job['id'])
            directory.mkdir(mode=0o700, exist_ok=True)
            with db.conn() as c:
                device = c.execute('SELECT * FROM p4_devices WHERE panel_id=?', (pid,)).fetchone()
            cfg = db.merged_config(pid)
            if not device or not device['enabled'] or shape(cfg) != job['shape']:
                set_state(job, 'superseded'); continue
            panel = db.get_panel(pid)
            background=cfg.get('display',{}).get('background',{})
            if background.get('mode')=='image':
                source=backgrounds.asset_path(background.get('image'))
                data=source.read_bytes()
                if hashlib.sha256(data).hexdigest()!=background['image']:raise ValueError('Background image verification failed')
                assets=directory/'private-assets';assets.mkdir(mode=0o700,exist_ok=True)
                (assets/('background-'+background['image']+'.webp')).write_bytes(data)
            cfg.update(_version=db.latest_version(pid), _panel_id=pid, _claimed=True)
            identity = dict(id=pid, mac=panel['mac'], server=device['server'], api_name=device['api_name'],
                            token=db.get_panel_token(pid), sign_key=db.get_panel_sign_key(pid), generation=job['id'])
            for name, value in [('config.json', {'config':cfg}), ('identity.json',identity), ('states.json', await ha.states())]:
                (directory/name).write_bytes(canonical(value))
                (directory/name).chmod(0o600)
            (directory/'api.key').write_text(device['api_key']); (directory/'api.key').chmod(0o600)
            set_state(job, 'building')
            with (directory/'build.log').open('wb') as log:
                process = await asyncio.create_subprocess_exec(sys.executable, str(SOURCE/'esphome/p4_runtime/build.py'), str(directory),
                    stdout=log, stderr=log, env=dict(os.environ, PYTHONUNBUFFERED='1'),start_new_session=os.name!='nt')
                code=await wait_build(process,job)
            if code is None:
                set_state(job,'superseded','Room changed during build; preparing its latest configuration')
                await asyncio.to_thread(trim_storage,pid)
                continue
            if code: raise RuntimeError('Build failed; the installed panel is unchanged. Private compiler log retained on server.')
            product = json.loads((directory/'product.json').read_bytes())
            await asyncio.to_thread(validate_product, product, directory/'artifacts')
            if shape(db.merged_config(pid)) != job['shape']:
                set_state(job, 'superseded'); continue
            manifest = dict(product, encryption=ENCRYPTION, _panel_id=pid, _claimed=True, _version=job['id'], mac=panel['mac'], config_version=cfg['_version'])
            (directory/'manifest.json').write_bytes(canonical(manifest))
            set_state(job, 'ready', 'Waiting for panel to stage and verify files')
            await asyncio.to_thread(trim_storage,pid)
        except asyncio.CancelledError: raise
        except Exception as error:
            if 'job' in locals(): set_state(job, 'failed', str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
            await asyncio.sleep(15)


def install(app, admin, owner, panel_auth, server_url):
    init()
    def paired(request, pid):
        # The legacy fleet permits first registration without a token. Update
        # downloads never inherit that exception, including unknown device IDs.
        if not db.get_panel_token(pid) or not db.get_panel_sign_key(pid):
            raise HTTPException(401, 'Paired device authentication required')
        panel_auth(request,pid)
    @app.on_event('startup')
    async def start(): app.state.p4_worker = asyncio.create_task(worker())
    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state, 'p4_worker', None)
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

    @app.get('/api/panels/{pid}/p4', dependencies=[Depends(admin)])
    async def read_status(pid: str): return status(pid)

    @app.get('/api/panels/{pid}/p4/log/{generation}', dependencies=[Depends(admin)])
    async def read_build_log(pid: str, generation: int):
        return Response(canonical(build_log(pid,generation)),media_type='application/json',headers={'Cache-Control':'no-store'})

    @app.post('/api/panels/{pid}/p4', dependencies=[Depends(admin), Depends(owner)])
    async def enroll(pid: str, request: Request):
        panel = db.get_panel(pid)
        if not panel or panel['kind'] != 'esp' or not panel['claimed'] or not panel.get('mac'):
            raise HTTPException(400, 'Choose a paired P4')
        b = await request.json()
        with db.conn() as c:
            old = c.execute('SELECT * FROM p4_devices WHERE panel_id=?', (pid,)).fetchone()
        key = b.get('api_key') or (old['api_key'] if old else '')
        if not key:raise HTTPException(400,'Enter the existing Home Assistant pairing key to preserve its connection')
        name = b.get('api_name') or (old['api_name'] if old else '')
        try:
            if len(base64.b64decode(key, validate=True)) != 32: raise ValueError()
        except (ValueError, TypeError): raise HTTPException(400, 'Invalid ESPHome identity')
        if not name:name=await existing_api_name(panel,key)
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',name):raise HTTPException(400,'Invalid ESPHome device name')
        with db.conn() as c:
            c.execute('INSERT OR REPLACE INTO p4_devices VALUES(?,?,?,?,?)', (pid,key,name,server_url(request),int(b.get('enabled',True))))
        access.audit(pid, 'admin', 'p4-enrollment', 'Automatic firmware and artwork deployment configured')
        queue(pid, retry=bool(b.get('retry')))
        return status(pid)

    @app.get('/api/p4/{pid}/release')
    async def release(pid: str, request: Request):
        paired(request, pid)
        with db.conn() as c:
            row = c.execute("SELECT b.id FROM p4_builds b JOIN p4_devices d ON d.panel_id=b.panel_id WHERE b.panel_id=? AND d.enabled=1 AND b.state IN ('ready','installed') ORDER BY b.id DESC LIMIT 1", (pid,)).fetchone()
        if not row: return Response(status_code=204)
        with db.conn() as c:
            built=c.execute('SELECT shape FROM p4_builds WHERE id=?',(row['id'],)).fetchone()
        if built['shape']!=shape(db.merged_config(pid)): return Response(status_code=204)
        body = (ROOT/str(row['id'])/'manifest.json').read_bytes()
        return Response(body, media_type='application/json', headers={'Cache-Control':'no-store',
            'X-Panel-Signature':hmac.new(db.get_panel_sign_key(pid).encode(),body,hashlib.sha256).hexdigest()})

    @app.get('/api/p4/{pid}/files/{generation}/{digest}')
    async def artifact(pid: str, generation: int, digest: str, request: Request):
        paired(request, pid)
        if not HEX.fullmatch(digest): raise HTTPException(404)
        with db.conn() as c:
            row = c.execute("SELECT id FROM p4_builds WHERE id=? AND panel_id=? AND state IN ('ready','installed')", (generation,pid)).fetchone()
        if not row: raise HTTPException(404)
        folder = ROOT/str(generation)
        manifest = json.loads((folder/'manifest.json').read_bytes())
        entry=next((f for f in [manifest['application'],*manifest['artwork']] if f['sha256']==digest),None)
        if not entry: raise HTTPException(404)
        offset=0; size=entry['bytes']; requested=request.headers.get('range','')
        if requested:
            match=re.fullmatch(r'bytes=(\d+)-',requested)
            if not match or not 0<=int(match[1])<size:raise HTTPException(416)
            offset=int(match[1])
        key=db.get_panel_sign_key(pid)
        def chunks():
            cipher=artifact_cipher(key,generation,digest,offset)
            with (folder/'artifacts'/(digest+'.bin')).open('rb') as stream:
                stream.seek(offset)
                while block:=stream.read(32768):yield cipher.update(block)
            yield cipher.finalize()
        headers={'Cache-Control':'private, no-store','Content-Length':str(size-offset)}
        if requested:headers['Content-Range']=f'bytes {offset}-{size-1}/{size}'
        return StreamingResponse(chunks(),status_code=206 if requested else 200,media_type='application/octet-stream',headers=headers)

    @app.post('/api/p4/{pid}/report')
    async def report(pid: str, request: Request):
        paired(request,pid)
        body = await request.body()
        if len(body)>1024: raise HTTPException(413)
        b = json.loads(body); generation=b.get('generation'); state=b.get('state')
        if type(generation)!=int or state not in ('staging','installing','installed','failed'): raise HTTPException(400)
        safe = {'generation':generation,'state':state,'at':time.time(),'detail':str(b.get('detail',''))[:120]}
        with db.conn() as c:
            row=c.execute('SELECT id,state FROM p4_builds WHERE id=? AND panel_id=?',(generation,pid)).fetchone()
            if not row: raise HTTPException(404)
            c.execute('UPDATE p4_builds SET report=? WHERE id=?',(json.dumps(safe),generation))
            if state in ('installed','failed'): c.execute('UPDATE p4_builds SET state=? WHERE id=?',(state,generation))
        if state in ('installed','failed') and row['state']!=state: access.audit(pid,'panel','p4-'+state,f'Build {generation}: '+safe['detail'])
        return {'ok':True}
