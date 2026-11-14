"""Capture Home's independent CM5 layers and exact CSS animation poses."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from PIL import Image
from render import fixture_page, W, H
from palette_art import PALETTES
from jpeg_motion import panel_jpeg


def capture(root, states, destination, cdp=None):
    destination.mkdir(parents=True, exist_ok=True)
    output=bytearray()
    frames=[]; poses=[]; colours=[]
    for palette in PALETTES:
        config=json.loads((root/palette/'config.json').read_bytes())
        config=config.get('config',config)
        config['display'].update(theme='architectural',palette=palette,screen_width=W,screen_height=H)
        current=[]
        with fixture_page(config,states,chromium_cdp=cdp) as page:
            # Runtime draws the live temperature and player. The photograph,
            # navigation, room title and menu keep Chromium's actual layering.
            page.add_style_tag(content='#archTemp,#roomMedia{visibility:hidden!important}')
            colour=page.evaluate("""()=>{const c=getComputedStyle(document.body);return {
                scrim:c.getPropertyValue('--scrim').trim(),ink:getComputedStyle(document.getElementById('archTemp')).color};}""")
            colours.append(colour)
            for phase in range(10):
                page.evaluate("document.getAnimations().forEach(a=>a.finish());document.querySelector('.nav [data-sheet=lights]').click()")
                page.wait_for_timeout(210)
                pose=page.evaluate("""t=>{
                    document.querySelector('#s-lights [data-close]').click();
                    document.getAnimations().forEach(a=>{a.pause();a.currentTime=t;});
                    const room=getComputedStyle(document.getElementById('room'));
                    return {scale:new DOMMatrix(room.transform).a,scrim:+getComputedStyle(document.getElementById('scrim')).opacity};
                }""",phase*18)
                png=page.screenshot()
                (destination/f'{palette}-{phase}.png').write_bytes(png)
                frame=panel_jpeg(Image.open(io.BytesIO(png)),quality=94,subsampling=2)
                frames.append([len(output),len(frame)]);output.extend(frame);current.append(pose)
            if poses and current!=poses:raise ValueError('Home motion differs between palettes')
            poses=current
        print('Captured Home zoom',palette,flush=True)
    digest=hashlib.sha256(output).hexdigest()
    (destination/(digest+'.bin')).write_bytes(output)
    def rgb(value):
        if value.startswith('#'):return [int(value[i:i+2],16) for i in (1,3,5)]
        return list(map(int,value.removeprefix('rgb(').removesuffix(')').split(',')))
    metadata=dict(sha256=digest,bytes=len(output),width=W,height=H,palettes=list(PALETTES),
                  frames=frames,poses=poses,colours=[{k:rgb(v) for k,v in colour.items()} for colour in colours],
                  motion='cm5-home-zoom',duration_ms=180,origin=[360,640])
    (destination/'home_zoom.json').write_text(json.dumps(metadata,indent=2))
    def packed(v):return (v[0]>>3)<<11 | (v[1]>>2)<<5 | (v[2]>>3)
    lines=['#pragma once','#include <cstdint>','namespace study {',
        f'constexpr char home_zoom_path[]="/sd/pi-panel/{digest}.bin";',
        'constexpr uint8_t home_zoom_sha[]={'+','.join(map(str,bytes.fromhex(digest)))+'};',
        f'constexpr unsigned home_zoom_size={len(output)},home_zoom_max_frame={max(f[1] for f in frames)};',
        'constexpr uint32_t home_zoom_frames[][2]={'+','.join('{%d,%d}'%tuple(f) for f in frames)+'};',
        'constexpr uint32_t home_zoom_scales[]={'+','.join(str(round(p['scale']*65536)) for p in poses)+'};',
        'constexpr uint8_t home_zoom_opacities[]={'+','.join(str(round(p['scrim']*255)) for p in poses)+'};',
        'constexpr uint16_t home_zoom_scrims[]={'+','.join(str(packed(c['scrim'])) for c in metadata['colours'])+'};',
        'constexpr uint16_t home_zoom_inks[]={'+','.join(str(packed(c['ink'])) for c in metadata['colours'])+'};','}']
    (destination/'home_zoom_assets.h').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print('Home zoom bytes',len(output),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('palettes',type=Path);parser.add_argument('states',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--chromium-cdp')
    args=parser.parse_args()
    capture(args.palettes,json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
