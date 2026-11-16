import copy,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'esphome/p4_runtime'))
import artwork_cache as cache

def main():
    config={'display':{'theme':'architectural','palette':'linen'},'lights':[{'entity_id':'light.one','name':'Lamp','soft':30}],
            'media':{'speakers':['media_player.one','media_player.two'],'default_speaker':'media_player.one'},'sensors':{},'doorbell':{}}
    states=[{'entity_id':'light.one','state':'on','attributes':{'brightness':200,'supported_color_modes':['color_temp']}}]
    key=cache.fingerprint(config,states)
    changed=copy.deepcopy(config);changed['display'].update(idle_timeout_s=100,adaptive_sensor='sensor.lux',palette='ember')
    changed['media']['default_speaker']='media_player.two';changed['sensors']['temperature']='sensor.temp';changed['_version']=99
    changed['connection']={'ha_url':'http://changed.local:8123'};changed['display']['dsi_overlay']='different-driver'
    assert cache.fingerprint(changed,states)==key
    changed['media'].update(default_speaker='media_player.new',default_speaker_name='New room',
        speakers=[{'entity_id':'media_player.new','name':'Renamed room'}])
    assert cache.fingerprint(changed,states)==key,'Live speaker list must reuse artwork'
    state=copy.deepcopy(states);state[0]['state']='off';state[0]['attributes']['brightness']=0
    assert cache.fingerprint(config,state)==key
    state[0]['attributes']['supported_color_modes']=['brightness'];assert cache.fingerprint(config,state)!=key
    changed['lights'][0]['name']='Another lamp';assert cache.fingerprint(changed,states)!=key
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);job=root/'job';job.mkdir();(job/'build').mkdir()
        for name in cache.BUILD_FILES:(job/'build'/name).write_bytes(('art-'+name).encode())
        for bank in cache.BANKS:
            (job/bank).mkdir();(job/bank/'sample.bin').write_bytes(b'bank');(job/bank/'sample.h').write_bytes(b'header')
        for name in cache.BANK_REQUIRED:(job/name).write_text('metadata')
        (job/'build/bench.key').write_text('never cache');(job/'identity.json').write_text('never cache')
        dest=root/'cache';cache.publish(dest,key,job)
        output=root/'output';assert cache.restore(dest,key,output)
        assert not (output/'build/bench.key').exists() and not (dest/key/'identity.json').exists()
        assert not list(dest.glob('stage-*'))
        (dest/key/'build/screens.bin').write_bytes(b'bad')
        assert not cache.restore(dest,key,root/'corrupt') and not (root/'corrupt').exists()
        manifest=dest/key/'manifest.json';m=json.loads(manifest.read_bytes());m['files'][0]['name']='../../outside.bin';manifest.write_text(json.dumps(m))
        assert not cache.restore(dest,key,root/'escape')
    print('PASS artwork reuse, visual/capability invalidation, complete verification, corruption rejection and credential exclusion')
if __name__=='__main__':main()
