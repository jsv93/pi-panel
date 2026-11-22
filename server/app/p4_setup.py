"""Admin-only first installation. Never re-enrol or reset an existing panel."""
import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from . import access, db, p4_config, p4_deployment as deploy

MAC = re.compile(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}')
OFFSETS = {'bootloader': (0x2000, 0x6000), 'partitions': (0x8000, 0x1000),
           'otadata': (0x9000, 0x2000), 'application': (0x10000, 0x300000),
           'nvs': (0x1f90000, 0x70000)}


def init():
    with db.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS p4_setup (panel_id TEXT PRIMARY KEY, created REAL NOT NULL)')


def initial_install(pid):
    with db.conn() as c:
        return bool(c.execute('SELECT 1 FROM p4_setup WHERE panel_id=?', (pid,)).fetchone() and
                    not c.execute("SELECT 1 FROM p4_builds WHERE panel_id=? AND state='installed'", (pid,)).fetchone())


def validate_probe(b):
    if not isinstance(b, dict) or b.get('schema') != 1 or b.get('chip') != 'ESP32-P4' or b.get('flash') != '32MB':
        raise ValueError('Connect a Waveshare ESP32-P4 with 32 MB flash')
    if type(b.get('revision')) is not int or not 100 <= b['revision'] < 300:
        raise ValueError('This chip revision needs a different firmware build')
    mac = b.get('mac', '')
    if not isinstance(mac, str) or not MAC.fullmatch(mac) or int(mac[:2], 16) & 1:
        raise ValueError('Invalid USB device identity')
    if b.get('installed') is not False:
        raise ValueError('Pi Panel is already installed. Use its normal update controls')
    return mac


def package(pid, generation):
    with db.conn() as c:
        row = c.execute("SELECT b.* FROM p4_builds b JOIN p4_setup s ON s.panel_id=b.panel_id "
                        "JOIN p4_devices d ON d.panel_id=b.panel_id WHERE b.panel_id=? AND b.id=? "
                        "AND b.state='ready' AND d.enabled=1", (pid, generation)).fetchone()
    if not row or not initial_install(pid):
        raise HTTPException(409, 'Only a new, not-yet-installed P4 can receive a USB installer')
    if not deploy.matches(row, db.merged_config(pid)):
        raise HTTPException(409, 'Settings changed. Wait for the new build')
    folder = deploy.ROOT/str(generation)
    try:
        product = json.loads((folder/'product.json').read_bytes())
        deploy.validate_product(product, folder/'artifacts')
        entries = product['usb']
        if len(entries) != 5 or {f['role'] for f in entries} != set(OFFSETS):
            raise ValueError('Incomplete USB product')
        files = []
        for entry in entries:
            offset, limit = OFFSETS[entry['role']]
            digest = entry['sha256']
            if entry['offset'] != offset or not deploy.HEX.fullmatch(digest): raise ValueError('Invalid USB product')
            path = folder/'artifacts'/(digest+'.bin')
            if path.is_symlink(): raise ValueError('Invalid USB product')
            data = path.read_bytes()
            if not 0 < len(data) <= limit or len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('USB artifact verification failed')
            if entry['role'] in ('nvs', 'otadata') and data != b'\xff'*limit:
                raise ValueError('Initial storage must be blank')
            files.append({**entry, 'data': base64.b64encode(data).decode()})
        # The application must be exactly the signed release used for artwork.
        app = next(f for f in files if f['role'] == 'application')
        if app['sha256'] != product['application']['sha256']: raise ValueError('Application mismatch')
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(409, 'A complete verified USB build is not available yet') from error
    panel = db.get_panel(pid)
    return dict(panel_id=pid, mac=panel['mac'], generation=generation, expires=int(time.time())+86400,
                room=panel['room'], files=files)


def install(app, admin, owner, server_url):
    init()

    @app.get('/api/p4-setup', dependencies=[Depends(admin)])
    async def setups():
        with db.conn() as c:
            rows = c.execute('SELECT s.panel_id,p.room FROM p4_setup s JOIN panels p ON p.id=s.panel_id ORDER BY s.created DESC').fetchall()
        return [dict(r) for r in rows]

    @app.post('/api/p4-setup', dependencies=[Depends(admin), Depends(owner)])
    async def create(request: Request):
        raw = await request.body()
        if len(raw) > 16384: raise HTTPException(413)
        try:
            b = json.loads(raw)
            if not isinstance(b, dict): raise ValueError('Invalid setup request')
            room = b.get('room', '').strip()
            if not 1 <= len(room) <= 60 or any(ord(c) < 32 for c in room): raise ValueError('Enter a room name of 1–60 characters')
            template=b.get('template','default')
            if not isinstance(template,str) or not db.get_template(template):raise ValueError('Choose an existing template')
            label=b.get('room_label') or room
            if not isinstance(label,str) or len(label)>60:raise ValueError('Room label must be at most 60 characters')
            cfg=db.deep_merge(db.DEFAULT_TEMPLATE,db.get_template(template))
            cfg=json.loads(json.dumps(cfg));cfg['room_label']=label
            cfg['display'].update(theme='architectural',screen_width=720,screen_height=1280)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise HTTPException(400, str(error)) from error
        # A deliberately forgotten/reset board gets a new identity. Old jobs
        # must never be reused with a newly issued token or signing key.
        pid = 'p4-'+secrets.token_hex(6)
        now = time.time()
        # The room exists before USB is selected, just like the Pi flow. No
        # compiler/device credentials are provisioned until USB identity binds.
        with db.conn() as c:
            c.execute('INSERT INTO panels(id,hostname,kind,room,template,claimed,first_seen,token,sign_key,token_claimed_at,token_claimed_from) VALUES(?,?,?,?,?,1,?,?,?,?,?)',
                      (pid,pid,'esp',room,template,now,secrets.token_urlsafe(32),secrets.token_urlsafe(32),now,'admin-usb-setup'))
            c.execute('INSERT INTO configs(panel_id,version,data,created_at) VALUES(?,1,?,?)', (pid,json.dumps(cfg),now))
            c.execute('INSERT INTO p4_setup VALUES(?,?)', (pid,now))
        access.audit(pid, 'admin', 'p4-setup', 'New P4 room created; awaiting USB installation')
        return dict(panel_id=pid)

    @app.get('/api/p4-setup/{pid}', dependencies=[Depends(admin)])
    async def progress(pid: str):
        with db.conn() as c:
            setup=c.execute('SELECT 1 FROM p4_setup WHERE panel_id=?',(pid,)).fetchone()
        if not setup:raise HTTPException(404,'This is an existing panel. Use its normal update controls')
        result=deploy.status(pid)
        panel=db.get_panel(pid)
        result.update(initial=initial_install(pid),mac=panel.get('mac'),ip=panel.get('ip'),metrics=panel.get('metrics') or {},last_seen=panel.get('last_seen'))
        return result

    @app.post('/api/p4-setup/{pid}/connect', dependencies=[Depends(admin), Depends(owner)])
    async def connect(pid: str, request: Request):
        if not initial_install(pid):raise HTTPException(409,'This panel has already been installed')
        raw=await request.body()
        if len(raw)>16384:raise HTTPException(413)
        try:
            mac=validate_probe(json.loads(raw))
            cfg=db.merged_config(pid);p4_config.validate(cfg)
            if not cfg.get('lights') or any(not re.fullmatch(r'light\.[a-z0-9_]+',x.get('entity_id','')) for x in cfg['lights']):
                raise ValueError('Save the room with 1–12 Home Assistant lights before installing')
            server=server_url(request).rstrip('/');parsed=urlsplit(server)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.hostname in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Set the Panel Server LAN URL in Settings before installing a P4')
        except (ValueError,TypeError,KeyError,AttributeError) as error:raise HTTPException(400,str(error)) from error
        with db.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            panel=c.execute('SELECT mac FROM panels WHERE id=?',(pid,)).fetchone()
            if not panel:raise HTTPException(404)
            if panel['mac'] and panel['mac']!=mac:raise HTTPException(409,'This room is already bound to a different P4')
            if c.execute('SELECT 1 FROM panels WHERE lower(mac)=? AND id!=?',(mac,pid)).fetchone():
                raise HTTPException(409,'This P4 already belongs to another panel. Nothing was written')
            c.execute('UPDATE panels SET mac=? WHERE id=?',(mac,pid))
            if not c.execute('SELECT 1 FROM p4_devices WHERE panel_id=?',(pid,)).fetchone():
                c.execute('INSERT INTO p4_devices VALUES(?,?,?,?,1)',(pid,base64.b64encode(secrets.token_bytes(32)).decode(),pid,server))
        access.audit(pid,'admin','p4-usb-connect','USB identity checked; preparing this room for installation')
        jobs=deploy.status(pid)['jobs']
        deploy.queue(pid,retry=bool(jobs and jobs[0]['state']=='failed'))
        return await progress(pid)

    @app.get('/api/p4-setup/{pid}/package/{generation}', dependencies=[Depends(admin), Depends(owner)])
    async def usb_package(pid: str, generation: int):
        payload = await asyncio.to_thread(package, pid, generation)
        access.audit(pid, 'admin', 'p4-usb-package', f'Firmware delivered to authenticated browser for build {generation}')
        return Response(deploy.canonical(payload),media_type='application/json',headers={'Cache-Control':'private, no-store'})

    @app.get('/api/p4-setup/{pid}/pairing', dependencies=[Depends(admin), Depends(owner)])
    async def pairing(pid: str):
        with db.conn() as c:
            row = c.execute('SELECT d.api_key,d.api_name FROM p4_devices d JOIN p4_setup s ON s.panel_id=d.panel_id WHERE d.panel_id=?', (pid,)).fetchone()
        if not row: raise HTTPException(404)
        access.audit(pid, 'admin', 'p4-pairing-view', 'Home Assistant encryption key viewed')
        return Response(deploy.canonical(dict(row)),media_type='application/json',headers={'Cache-Control':'no-store'})
