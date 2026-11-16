"""Live settings don't build, remain authenticated, and reject unsafe inputs."""
import asyncio,copy,json,os,sys,tempfile,time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
async def check(server,db,deploy):
    pid='p4-live';db.upsert_panel(pid,pid,'aa:bb:cc:dd:ee:ff','192.0.2.1','esp','native-p4')
    db.claim(pid,'study','default','Study')
    cfg=db.merged_config(pid);cfg['display']['theme']='architectural'
    cfg['lights']=[dict(entity_id='light.test',name='Test',soft=20,bright=100)]
    cfg['doorbell']=dict(enabled=False,camera='',trigger='',duration_s=30,title='Doorbell')
    cfg['media'].update(default_speaker='media_player.one',speakers=['media_player.one','media_player.two'])
    db.save_config(pid,cfg)
    with db.conn() as c:c.execute('INSERT INTO p4_devices(panel_id,api_key,api_name,server) VALUES(?,?,?,?)',(pid,'key',pid,'http://localhost'))
    deploy.queue(pid);start=deploy.status(pid)['jobs'][0]['id']
    from app import p4_config
    legacy=copy.deepcopy(cfg);legacy['media']['default_speaker']='media_player.legacy'
    assert p4_config.compatible(cfg,legacy)
    unknown=copy.deepcopy(cfg);unknown['media']['default_speaker']='media_player.new'
    assert p4_config.compatible(unknown,legacy)
    empty=copy.deepcopy(cfg);empty.pop('doorbell');empty.pop('sensors')
    first=copy.deepcopy(empty);first['doorbell']=dict(enabled=True,camera='camera.first',title='');first['sensors']={'temperature':'sensor.first'}
    assert deploy.shape(first)==deploy.shape(empty),'First-time runtime assignments must not require artwork'
    edits={'display':dict(idle_timeout_s=120,backlight_off_s=10,backlight_default=60,backlight_min=8,
        adaptive_brightness=True,adaptive_sensor='sensor.lux',adaptive_min_pct=12,adaptive_max_pct=80,
        adaptive_dark_lux=2,adaptive_bright_lux=800,adaptive_transition_s=9,p4_presence_pin=2,p4_presence_debounce_ms=1500),
        'doorbell':dict(enabled=True,camera='camera.other',trigger='binary_sensor.ring',duration_s=60),
        'sensors':dict(temperature='sensor.temp',humidity='sensor.hum',climate='climate.other'),
        'media':dict(default_speaker='media_player.new',default_speaker_name='New name',
            speakers=[dict(entity_id='media_player.new',name='New name'),'media_player.one'])}
    server.SESSIONS['live-test']=time.time()+60
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://localhost') as c:
        route=f'/api/panels/{pid}/config'
        assert (await c.put(route,json=cfg)).status_code==401
        c.cookies.set('psid','live-test')
        for section,values in edits.items():
            for key,value in values.items():
                candidate=copy.deepcopy(cfg);candidate[section][key]=value
                # Enable requires a sensor/camera in the same atomic update.
                if key=='adaptive_brightness':candidate['display']['adaptive_sensor']='sensor.lux'
                if key=='enabled':candidate['doorbell']['camera']='camera.other'
                response=await c.put(route,json=candidate);assert response.is_success,(section,key,response.text)
                deploy.queue(pid);assert deploy.status(pid)['jobs'][0]['id']==start,(section,key)
        for key,value in [('p4_presence_pin',7),('p4_presence_pin',True),('p4_presence_debounce_ms',0),
                          ('adaptive_min_pct',101),('backlight_default',0),('idle_timeout_s',-1)]:
            before=db.latest_version(pid)
            bad=copy.deepcopy(cfg);bad['display'][key]=value
            assert (await c.put(route,json=bad)).status_code==400,(key,value)
            assert db.latest_version(pid)==before
        # Firmware layout/hardware still requires rebuilding.
        for section,key,value in [('display','dsi_overlay','different'),('display','screen_width',800),
                                   ('doorbell','title','Front Door')]:
            changed=copy.deepcopy(cfg);changed[section][key]=value
            assert deploy.shape(changed)!=deploy.shape(cfg),(section,key)
        for speakers in ([{'entity_id':'switch.bad','name':'Bad'}],['media_player.one']*2,
                          ['media_player.s'+str(i) for i in range(17)],
                          [{'entity_id':'media_player.one','name':'a'*97}]):
            bad=copy.deepcopy(cfg);bad['media']['speakers']=speakers
            before=db.latest_version(pid)
            assert (await c.put(route,json=bad)).status_code==400
            assert db.latest_version(pid)==before
        db.upsert_panel('pi','pi','','192.0.2.2','pi','test');db.claim('pi','study','default','Study')
        pi=db.merged_config('pi');pi['display'].update(presence_pin=26,browser_recovery=False,browser_stale_s=120)
        assert (await c.put('/api/panels/pi/config',json=pi)).is_success
        assert db.merged_config('pi')['display']['presence_pin']==26
    print('PASS live-setting classification, authentication, atomic rejection, structural rebuilds and Pi preservation')

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp:
        os.environ.update(PANEL_DB=str(Path(temp)/'panel.db'),PANEL_P4_DATA=str(Path(temp)/'p4'))
        sys.path.insert(0,str(ROOT/'server'))
        from app import main,db,p4_deployment
        asyncio.run(check(main,db,p4_deployment))
