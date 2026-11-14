"""Private per-device build worker used by Panel Server (no flashing or publishing).

Inputs in JOB: config.json, states.json, identity.json and api.key. Everything
produced stays in JOB. Credentials and household artwork are never GitHub artifacts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/'esphome/study'
HARDWARE='waveshare-p4-wifi6-32mb-5dsi-720x1280-v1'


def build(job):
    os.environ['PANEL_RENDER_ASSET_DIR']=str(job/'private-assets')
    sys.path.insert(0,str(STUDY))
    from render import generate
    from control_art import capture as controls
    from media_art import capture as media
    from overlay_capture import capture,capture_text,capture_volume,capture_wifi
    from overlay_art import build as overlays
    from palette_art import PALETTES,encode
    from palette_runtime import build as palettes
    from sd_navigation import build as navigation
    from home_zoom import capture as home
    config=json.loads((job/'config.json').read_bytes())['config']
    states=json.loads((job/'states.json').read_bytes())
    identity=json.loads((job/'identity.json').read_bytes())
    if config.get('display',{}).get('theme')!='architectural':raise ValueError('Select the Architectural theme for this P4')
    if not 1<=len(config.get('lights',[]))<=12:raise ValueError('This P4 layout supports 1–12 Home Assistant lights')
    if config.get('dali',{}).get('enabled') or config.get('dali',{}).get('gateway'):raise ValueError('DALI is not enabled in this P4 firmware')
    build=job/'build';build.mkdir(exist_ok=True)
    output=job/'artifacts';output.mkdir(exist_ok=True)
    render_root=job/'palettes';capture_root=job/'overlays'
    env=dict(os.environ,PYTHONUTF8='1',PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'])
    def phase(name):
        temp=job/'progress.part';temp.write_text(json.dumps(dict(phase=name,at=time.time())))
        temp.replace(job/'progress.json')
        print(name,flush=True)
    def run(script,*args):
        subprocess.run([sys.executable,str(script),*map(str,args)],env=env,check=True)
    phase('Rendering pages')
    for palette in PALETTES:
        cfg=json.loads(json.dumps(config));cfg['display'].update(palette=palette,screen_width=720,screen_height=1280)
        directory=render_root/palette;directory.mkdir(parents=True,exist_ok=True)
        (directory/'config.json').write_text(json.dumps({'config':cfg}))
        generate(cfg,states,directory)
    for path in (render_root/'linen').iterdir():
        if path.is_file():shutil.copyfile(path,build/path.name)
    linen=json.loads((render_root/'linen/config.json').read_bytes())['config']
    phase('Rendering controls')
    controls(linen,states,build);media(linen,states,build)
    phase('Rendering popup artwork')
    for palette in PALETTES:
        cfg=json.loads(json.dumps(config));cfg['display'].update(palette=palette,browse_view='tiles',screen_width=720,screen_height=1280)
        destination=capture_root/palette;destination.mkdir(parents=True,exist_ok=True)
        capture_text(cfg,states,destination,architectural_only=True)
        capture(cfg,states,destination);capture_volume(cfg,states,destination);capture_wifi(cfg,states,destination)
    for name in ('text_art.h','text-art.bin'):shutil.copyfile(capture_root/'linen'/name,build/name)
    phase('Packing palettes')
    encode(render_root,job/'palette-source.bin')
    palettes(render_root,job/'palette-source.bin',states,build)
    (build/'bench.key').write_bytes((job/'api.key').read_bytes())
    run(STUDY/'firmware.py',build,'--sd-only')
    overlays(build,capture_root,job/'overlay-assets',capture_root)
    phase('Packing transitions')
    navigation(render_root,job/'navigation-assets',max(1,min(4,int(os.environ.get('P4_BUILD_WORKERS','1')))))
    home(render_root,states,job/'home-assets')
    phase('Preparing firmware')
    run(Path(__file__).with_name('prepare.py'),build,job/'config.json','--id',identity['id'],'--mac',identity['mac'],
        '--server',identity['server'],'--identity-file',job/'identity.json','--hosted-wifi','--architectural-only','--sd-only','--production',
        '--overlay-assets',job/'overlay-assets','--navigation-assets',job/'navigation-assets','--home-zoom-assets',job/'home-assets')
    phase('Compiling firmware')
    subprocess.run([sys.executable,'-m','esphome','compile',str(build/'study-live.yaml')],env=env,check=True)
    name=identity.get('api_name','p4-study-bench')
    firmware=build/f'.esphome/build/{name}/.pioenvs/{name}/firmware.ota.bin'
    def artifact(path,role):
        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if not data:raise ValueError('Empty '+role+' artifact')
        destination=output/(digest+'.bin');shutil.copyfile(path,destination)
        return dict(role=role,sha256=digest,bytes=len(data))
    app=artifact(firmware,'application')
    if app['bytes']>0x300000:raise ValueError('Room firmware exceeds the P4 application slot; the current panel is unchanged')
    files=[]
    for bank in json.loads((build/'sd-assets/local-banks.json').read_bytes()):
        files.append(artifact(build/'sd-assets'/(bank['sha256']+'.bin'),bank['name']))
    for role,folder,manifest in [('navigation','navigation-assets','navigation.json'),('home','home-assets','home_zoom.json')]:
        m=json.loads((job/folder/manifest).read_bytes());files.append(artifact(job/folder/(m['sha256']+'.bin'),role))
    # The overlay packer uses a single immutable hash-named bank.
    banks=list((job/'overlay-assets').glob('*.bin'))
    if len(banks)!=1:raise ValueError('Ambiguous overlay bank')
    files.append(artifact(banks[0],'overlays'))
    result=dict(hardware=HARDWARE,application=app,artwork=files,api_name=name)
    (job/'product.json').write_text(json.dumps(result,indent=2))
    phase('Ready')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('job',type=Path)
    args=parser.parse_args()
    if hasattr(os,'nice'):os.nice(10)
    build(args.job.resolve())
