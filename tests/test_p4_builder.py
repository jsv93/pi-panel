"""Compile a complete synthetic room inside the release image; no household data."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from app.db import DEFAULT_TEMPLATE

def main():
    with tempfile.TemporaryDirectory() as temporary:
        job=Path(temporary)
        config=json.loads(json.dumps(DEFAULT_TEMPLATE))
        config.update(room_label='Test room',_version=1,_panel_id='p4-ci',_claimed=True,
            lights=[dict(entity_id='light.test',name='Test lamp',soft=30,bright=100,include_presets=True)],
            sensors=dict(temperature='sensor.test_temperature',humidity='sensor.test_humidity',climate='climate.test'),
            media=dict(default_speaker='media_player.test',default_speaker_name='Test speaker',speakers=[dict(entity_id='media_player.test',name='Test speaker')]),
            doorbell=dict(enabled=True,title='Doorbell',camera='camera.test',trigger='',duration_s=30),
            connection=dict(ha_url='http://homeassistant.invalid:8123'))
        config['display'].update(theme='architectural',palette='linen',screen_width=720,screen_height=1280,browse_view='tiles')
        states=[dict(entity_id=entity,state=state,attributes=attrs) for entity,state,attrs in [
            ('light.test','on',dict(brightness=255,supported_color_modes=['color_temp'],color_mode='color_temp',color_temp_kelvin=3000,min_color_temp_kelvin=2000,max_color_temp_kelvin=6500)),
            ('sensor.test_temperature','22',{}),('sensor.test_humidity','45',{}),
            ('climate.test','off',dict(temperature=22,current_temperature=22,min_temp=16,max_temp=30,hvac_modes=['off','cool','heat'])),
            ('media_player.test','idle',dict(friendly_name='Test speaker',volume_level=.2,supported_features=517055)),
            ('camera.test','idle',{})]]
        identity=dict(id='p4-ci',mac='02:00:00:00:00:01',server='http://panel.invalid:8099',api_name='p4-ci',token='fixture-only-token',sign_key='fixture-only-signing-key',generation=1)
        for name,value in [('config.json',{'config':config}),('states.json',states),('identity.json',identity)]:
            (job/name).write_text(json.dumps(value))
        (job/'api.key').write_text(base64.b64encode(bytes(range(32))).decode())
        source=Path(os.environ.get('PANEL_P4_SOURCE',str(ROOT)))
        subprocess.run([sys.executable,str(source/'esphome/p4_runtime/build.py'),str(job)],check=True)
        product=json.loads((job/'product.json').read_bytes())
        assert product['application']['bytes']<=0x300000
        assert {f['role'] for f in product['artwork']}=={'volume','text','palette','navigation','home','overlays'}
        print('PASS portable complete-room rendering and firmware compilation')

if __name__=='__main__':main()
