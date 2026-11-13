"""Build a native-resolution transition bank with shared JPEG restart segments."""
from pathlib import Path
import hashlib
import io
import json
import re
import sys
import zlib
import numpy as np
from PIL import Image
from page_motion import W,H,routes,pose

def panel_jpeg(image, **options):
    """Encode for the P4 JPEG DMA's video-range BT.601 to RGB converter."""
    y = [16 + round(v * 219 / 255) for v in range(256)]
    chroma = [128 + round((v - 128) * 224 / 255) for v in range(256)]
    planes = image.convert("YCbCr").point(y + chroma + chroma)
    output = io.BytesIO()
    planes.save(output, "JPEG", **options)
    return output.getvalue()

def motion_sources(d,views):
    art=(d/"screens.bin").read_bytes()
    pages=[]
    for v in views:
        source=d/(v["name"]+"-rgb.png")
        if source.exists():
            with Image.open(source) as im:
                if im.size!=(W,H):raise ValueError(f"Unexpected source dimensions: {source}")
                pages.append(im.convert("RGB"))
        else:
            raw=zlib.decompress(art[v["offset"]:v["offset"]+v["size"]])
            pages.append(Image.frombytes("RGB",(W,H),raw,"raw","BGR;16"))
    return pages

def motion_image(bg,fg,step,travel,clip):
    # Blend before display quantization so the JPEG encoder sees a smooth gradient.
    shift,alpha=pose(step,travel)
    shifted=bg.copy()
    shifted.paste(fg,(shift,0))
    image=Image.blend(bg,shifted,alpha/32)
    if clip<H:image.paste(fg.crop((0,clip,W,H)),(0,clip))
    return image

def build(d):
    views=json.loads((d/"screens.json").read_text())["views"]
    pages=motion_sources(d,views)
    clips=[min([l["y"] for l in v["links"] if l["root"]]+[H]) for v in views]
    idx={};segments=bytearray();offsets=[0];maps=bytearray();paths=[]
    prefix=None;max_size=0
    for a,b,travel in routes(views):
        phases=[]
        for step in range(10):
            image=motion_image(pages[a],pages[b],step,travel,clips[b])
            raw=panel_jpeg(image,quality=94,subsampling=2,restart_marker_blocks=1)
            max_size=max(max_size,len(raw))
            sos=raw.index(b'\xff\xda')+2
            start=sos+int.from_bytes(raw[sos:sos+2],"big")
            if prefix is None:prefix=raw[:start]
            assert prefix==raw[:start] and raw[-2:]==b'\xff\xd9'
            blocks=re.split(rb'\xff[\xd0-\xd7]',raw[start:-2])
            assert len(blocks)==(W//16)*(H//16)
            codes=[]
            for block in blocks:
                k=idx.get(block)
                if k is None:
                    k=len(idx);idx[block]=k;segments.extend(block);offsets.append(len(segments))
                codes.append(k)
            packed=zlib.compress(np.asarray(codes,dtype="<u4").tobytes(),3)
            phases.append((len(maps),len(packed)));maps.extend(packed)
        paths.append((a,b,travel,phases))
    raw=prefix+segments+maps
    print(f"{len(paths)} routes, {len(idx)} distinct segments; {len(segments)} entropy bytes, {len(maps)} map bytes, {len(offsets)*4} index bytes, max frame {max_size}",flush=True)
    (d/"jpeg_bank.bin").write_bytes(raw)
    (d/"jpeg_meta.json").write_text(json.dumps([len(prefix),len(segments),max_size,paths]))
    np.asarray(offsets,dtype="<u4").tofile(d/"jpeg_offsets.bin")

def fingerprint(d):
    digest=hashlib.sha256(Path(__file__).read_bytes())
    for p in (Path(__file__).with_name("page_motion.py"),d/"screens.json",d/"screens.bin"):
        digest.update(p.read_bytes())
    for v in json.loads((d/"screens.json").read_text())["views"]:
        p=d/(v["name"]+"-rgb.png")
        if p.exists():digest.update(p.read_bytes())
    return digest.hexdigest()

def emit(d):
    prefix,entropy,maximum,paths=json.loads((d/"jpeg_meta.json").read_text())
    bank=(d/"jpeg_bank.bin").read_bytes()
    offsets=(d/"jpeg_offsets.bin").read_bytes()
    ends=np.frombuffer(offsets,"<u4")
    lengths=np.diff(ends)
    if not len(lengths) or ends[0] or ends[-1]!=entropy or np.any(lengths>255):
        raise ValueError("Unexpected motion segment length")
    # A checkpoint and 16 one-byte lengths replace 16 four-byte offsets.
    # The decoder sums at most 15 lengths for a random segment.
    checkpoints=ends[:-1:16].astype("<u4").tobytes()
    packed_index=checkpoints+lengths.astype("u1").tobytes()
    payload=packed_index+bank
    tag=hashlib.sha256(payload).digest()
    image=tag+payload
    if len(image)>0x1980000:raise ValueError("Motion asset exceeds its data partition")
    (d/"study-motion.bin").write_bytes(image)
    m=json.loads((d/"screens.json").read_text())
    art=(d/"screens.bin").read_bytes()
    def pix(v):
        return np.frombuffer(zlib.decompress(art[v["offset"]:v["offset"]+v["size"]]),"<u2").reshape(v["h"],v["w"])
    scene_base=pix(next(v for v in m["views"] if v["name"]=="scenes"))
    scenes=np.logical_or.reduce([pix(v)!=scene_base for v in m["scene_sprites"]])
    lamps=np.zeros((H,W),dtype=bool)
    for j,key in enumerate(("reading","slider")):
        r=m[key];x,y=r["x"],r["y"]
        reference=pix(m["patches"][0][j])
        mask=np.logical_or.reduce([pix(p[j])!=reference for p in m["patches"]])
        for v in m["views"]:
            if re.fullmatch(r"light\d+",v["name"]):
                mask|=pix(v)[y:y+r["height"],x:x+r["width"]]!=reference
        lamps[y:y+r["height"],x:x+r["width"]]=mask
    with (d/"navigation_assets.h").open("w",encoding="ascii") as h:
        h.write("#pragma once\n#include <cstdint>\nnamespace study {\n")
        h.write("struct Block {uint32_t offset,size,bytes;};struct PathMotion {int from,to,travel; Block phases[10];};\n")
        entries=[]
        for a,b,t,phases in paths:
            blocks=[]
            for o,s in phases:
                ids=np.frombuffer(zlib.decompress(bank[prefix+entropy+o:prefix+entropy+o+s]),"<u4")
                n=prefix+int(lengths[ids].sum())+2*len(ids)
                blocks.append("{%d,%d,%d}"%(o,s,n))
            entries.append("{%d,%d,%d,{%s}}"%(a,b,t,",".join(blocks)))
        h.write("constexpr PathMotion nav_paths[]={"+",".join(entries)+"};\n")
        h.write("constexpr uint8_t motion_tag[]={"+",".join(map(str,tag))+"};\n")
        h.write(f"#define STUDY_PACKED_SEGMENTS\nconstexpr size_t checkpoint_bytes={len(checkpoints)};\n")
        h.write(f"constexpr size_t motion_bytes={len(image)}, offsets_bytes={len(packed_index)}, header_bytes={prefix}, entropy_bytes={entropy}, max_frame={maximum};\n")
        h.write("struct Pose {int shift; unsigned alpha;};constexpr Pose nav_pose[3][11]={"+
                ",".join("{"+",".join("{%d,%d}"%pose(i,t) for i in range(11))+"}" for t in (14,24,-24))+"};\n")
        h.write("constexpr const char *page_names[]={"+",".join(json.dumps(v["name"]) for v in m["views"])+"};\n")
        for name,mask in (("scene",scenes),("lamp",lamps)):
            bits=mask.reshape(H//8,8,W//16,16).any(axis=(1,3))
            h.write("constexpr uint8_t "+name+"_changes[]={"+",".join(map(str,np.packbits(bits.ravel(),bitorder="little")))+"};\n")
        h.write("}\n")
    (d/"navigation.sha256").write_text(fingerprint(d))
    print(f"{len(image):,} bytes in the dedicated motion partition",flush=True)

def ensure(d):
    stamp=d/"navigation.sha256"
    if not (stamp.exists() and stamp.read_text()==fingerprint(d) and (d/"study-motion.bin").exists() and (d/"navigation_assets.h").exists()):
        build(d);emit(d)

if __name__=="__main__":
    d=Path(sys.argv[1])
    if "--emit-only" not in sys.argv:build(d)
    emit(d)
