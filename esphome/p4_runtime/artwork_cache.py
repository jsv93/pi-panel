"""Verified, per-device render cache. Never stores credentials or firmware."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
from app.p4_config import structural

BUILD_FILES=('screens.bin','screens.json','control_art.h','media_art.h','text_art.h',
    'text-art.bin','volume-art.bin','palette_assets.h','palette-art.bin','mini_player.h','identify_assets.h')
BANKS=('overlay-assets','navigation-assets','home-assets')
BANK_REQUIRED=('overlay-assets/overlay_assets.h','navigation-assets/navigation_art_assets.h',
               'navigation-assets/navigation.json','home-assets/home_zoom_assets.h','home-assets/home_zoom.json')

def fingerprint(config,states):
    shape=structural(config)
    # Connection endpoints and Pi hardware options can require new firmware
    # without changing any rendered pixels. Resolution remains visual.
    shape.pop('connection',None);shape.pop('bluetooth',None)
    shape.get('display',{}).pop('dsi_overlay',None)
    # Every supported palette and both library views are rendered together.
    # State values are runtime data; capabilities that alter controls are not.
    ids={v.get('entity_id') for v in config.get('lights',[])}
    capabilities={s['entity_id']:{k:v for k,v in s.get('attributes',{}).items()
        if k in ('supported_color_modes','min_color_temp_kelvin','max_color_temp_kelvin','supported_features')}
        for s in states if s.get('entity_id') in ids}
    h=hashlib.sha256(json.dumps([3,shape,capabilities],sort_keys=True,separators=(',',':')).encode())
    sources=list((ROOT/'esphome/study').glob('*.py'))
    sources=[p for p in sources if p.name not in ('firmware.py','sd_firmware.py')]
    sources+=list((ROOT/'panel-ui').glob('*'))
    for path in sorted(p for p in sources if p.is_file()):
        h.update(str(path.relative_to(ROOT)).replace('\\','/').encode());h.update(path.read_bytes())
    return h.hexdigest()

def allowed(name):
    p=PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and '\\' not in name and
        ((len(p.parts)==2 and p.parts[0]=='build' and p.name in BUILD_FILES) or
         (len(p.parts)==2 and p.parts[0] in BANKS and p.suffix in ('.h','.json','.bin'))))

def restore(cache,key,job):
    entry=Path(cache)/key
    try:
        if entry.is_symlink():return False
        manifest=json.loads((entry/'manifest.json').read_bytes())
        if manifest['key']!=key or not manifest['files']:return False
        files=manifest['files']
        for item in files:
            name=item['name'];path=entry/name
            if not allowed(name) or path.is_symlink() or not path.resolve().is_relative_to(entry.resolve()):return False
            if path.stat().st_size!=item['bytes']:return False
            with path.open('rb') as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=item['sha256']:return False
        required={f'build/{n}' for n in BUILD_FILES}
        required.update(BANK_REQUIRED)
        if not required.issubset({f['name'] for f in files}):return False
        for bank in BANKS:
            if not any(f['name'].startswith(bank+'/') and f['name'].endswith('.bin') for f in files):return False
        # Verify the complete entry before touching the new job.
        for item in files:
            dest=job/item['name'];dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(entry/item['name'],dest)
        return True
    except (OSError,ValueError,KeyError,TypeError):return False

def publish(cache,key,job):
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Only explicit render products are eligible, never config/identity/source.
    paths=[job/'build'/name for name in BUILD_FILES]
    paths += [p for bank in BANKS for p in (job/bank).iterdir() if p.suffix in ('.h','.json','.bin')]
    with tempfile.TemporaryDirectory(prefix='stage-',dir=cache) as temp:
        stage=Path(temp);items=[]
        for path in paths:
            name=path.relative_to(job).as_posix()
            if not allowed(name) or path.is_symlink():raise ValueError('Invalid artwork cache input')
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            items.append(dict(name=name,bytes=target.stat().st_size,sha256=digest))
        (stage/'manifest.json').write_text(json.dumps(dict(key=key,files=items)))
        target=cache/key
        if target.exists():
            if target.is_symlink() or target.resolve().parent!=cache.resolve():raise ValueError('Unsafe cache target')
            shutil.rmtree(target)
        stage.rename(target)
