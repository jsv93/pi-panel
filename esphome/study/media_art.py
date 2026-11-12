"""Export the CM5 media volume popup and all percentage positions losslessly."""
import io
import json
from pathlib import Path
import sys
import struct
import zlib

import numpy as np
from PIL import Image
from render import fixture_page,rgb565
from control_art import box


def capture(config,states,dest):
    with fixture_page(config,states) as page:
        page.locator('.nav [data-sheet=media]').evaluate("e=>e.click()")
        page.wait_for_timeout(360)
        toggle=box(page,"#mpVolumeButton")
        page.locator("#mpVolumeButton").evaluate("e=>e.click()")
        page.wait_for_timeout(300)
        popup=box(page,"#mpVolumePopup");slider=box(page,"#mVol");close=box(page,"#mpVolumeClose")
        page.add_style_tag(content="#s-media *{transition:none!important}")
        tiles={};refs=[];bank=bytearray();frames=[];bases=[]
        for level in range(101):
            page.evaluate("""v=>{
              for(const id of ['mpVolumeValue','mpVolumeReadout'])document.getElementById(id).textContent=v+'%';
              const e=document.getElementById('mVol');
              e.querySelector('.fill').style.transform='scaleX('+v/100+')';
              e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%),-50%)';
            }""",level)
            img=Image.open(io.BytesIO(page.screenshot()))
            page.locator("#mpVolumePopup").evaluate("e=>e.style.visibility='hidden'")
            closed=Image.open(io.BytesIO(page.screenshot()))
            page.locator("#mpVolumePopup").evaluate("e=>e.style.visibility=''")
            pair=[]
            for group,((x,y,w,h),source) in enumerate(((toggle,closed),(popup,img))):
                pix=np.frombuffer(rgb565(source.crop((x,y,x+w,y+h)),x,y),"<u2").reshape(h,w)
                if level==0:bases.append(pix.copy())
                delta=pix^bases[group]
                ids=[]
                for px in range(0,w,16):
                    data=delta[:,px:px+16].tobytes()
                    if data not in tiles:
                        tiles[data]=len(tiles)
                    ids.append(tiles[data])
                pair.append(ids)
            frames.append(pair)
    def arr(v):
        return "{"+",".join(arr(k) if isinstance(k,(tuple,list)) else str(k) for k in v)+"}"
    palette={};patterns=bytearray()
    for raw in tiles:
        codes=bytearray()
        for off in range(0,len(raw),16):
            pattern=raw[off:off+16].ljust(16,b'\0')
            if pattern not in palette:
                palette[pattern]=len(palette);patterns.extend(pattern)
            codes+=struct.pack("<H",palette[pattern])
        data=zlib.compress(codes,9);refs.append((len(bank),len(data)));bank.extend(data)
    packed=zlib.compress(patterns,9)
    palette_ref=(len(bank),len(packed));bank.extend(packed)
    base_refs=[]
    for pix in bases:
        data=zlib.compress(pix.tobytes(),9);base_refs.append((len(bank),len(data)));bank.extend(data)
    data='\n'.join('"'+''.join(f'\\x{b:02x}' for b in bank[o:o+256])+'"' for o in range(0,len(bank),256))
    path=dest/"media_art.h"
    with path.open("w",encoding="ascii") as f:
        f.write('#pragma once\n#include "study_assets.h"\nnamespace study {\n')
        f.write("static const unsigned char volume_art[]=\n"+data+";\n")
        f.write("struct VolumeStrip {unsigned offset;unsigned short size;};\nconstexpr VolumeStrip volume_tiles[]="+arr(refs)+";\n")
        f.write("constexpr VolumeStrip volume_bases[]="+arr(base_refs)+";\n")
        f.write("constexpr VolumeStrip volume_dictionary="+arr(palette_ref)+";\n")
        f.write(f"constexpr size_t volume_dictionary_size={len(patterns)};\n")
        for i,(name,r) in enumerate((("button",toggle),("popup",popup))):
            f.write(f"constexpr uint16_t volume_{name}_tiles[][{len(frames[0][i])}]="+arr([p[i] for p in frames])+";\n")
            f.write(f"constexpr Rect volume_{name}="+arr(r)+";\n")
        f.write("constexpr Rect volume_slider="+arr(slider)+",volume_close="+arr(close)+";\n}\n")
    print("Volume graphics",len(bank),"bytes,",len(refs),"unique strips")


if __name__=="__main__":
    cfg,states,dest=map(Path,sys.argv[1:])
    capture(json.loads(cfg.read_bytes())["config"],json.loads(states.read_bytes()),dest)
