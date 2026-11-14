"""Losslessly share repeated sixteen-byte pixel patterns across one widget."""
import re
import struct
import zlib
import numpy as np


def pack(bank,tables):
    # NumberGlyph records also point into this bank. Rebuild every offset in
    # one pass so no original bytes need to be retained just for those masks.
    result=bytearray()
    offsets={}
    def put(data):
        if data not in offsets:
            offsets[data]=len(result);result.extend(data)
        return offsets[data]
    def get(off,size):return bytes(bank[off:off+size])
    record=re.compile(r"\{(\d+),(\d+),(\d+),(\d+)\}")
    def original(key):
        off,size,w,h=key
        if not size:return key
        if not size>>31:return put(get(off,size)),size,w,h
        base,n,x,y,cw,ch=struct.unpack_from("<IIHHHH",bank,off)
        patch=struct.pack("<IIHHHH",put(get(base,n)),n,x,y,cw,ch)+get(off+16,(size&0x7fffffff)-16)
        return put(patch),size,w,h
    def pixels(key):
        off,size,w,h=key
        if not size>>31:return zlib.decompress(get(off,size))
        base,n,x,y,cw,ch=struct.unpack_from("<IIHHHH",bank,off)
        frame=np.frombuffer(zlib.decompress(get(base,n)),"<u2").reshape(h,w).copy()
        patch=zlib.decompress(get(off+16,(size&0x7fffffff)-16))
        frame[y:y+ch,x:x+cw]=np.frombuffer(patch,"<u2").reshape(ch,cw)
        return frame.tobytes()
    grouped={"climate_positions","row_labels","backlight_modes","warmth_modes","hue_modes"}
    for i,line in enumerate(tables):
        if line.startswith("constexpr NumberGlyph "):
            glyph=re.compile(r"\{(\d+),(\d+),(-?\d+),(-?\d+),(\d+),(\d+),(-?\d+)\}")
            tables[i]=glyph.sub(lambda m:"{"+",".join([str(put(get(int(m[1]),int(m[2])))),*m.groups()[1:]])+"}",line)
        if not line.startswith("constexpr Sprite "):continue
        keys=list(dict.fromkeys(tuple(map(int,m.groups())) for m in record.finditer(line)))
        mapping={}
        if line.split()[2].split("[")[0] in grouped:
            valid=[k for k in keys if k[1]]
            raw=[pixels(k) for k in valid]
            items=[np.frombuffer(p+b'\0'*(-len(p)%16),dtype="V16") for p in raw]
            if items:
                palette,indices=np.unique(np.concatenate(items),return_inverse=True)
                if len(palette)<=65535:
                    data=zlib.compress(palette.tobytes(),9);pos=0
                    handle=struct.pack("<III",put(data),len(data),palette.nbytes)
                    for k,arr,ref in zip(valid,items,raw):
                        codes=indices[pos:pos+len(arr)].astype("<u2");pos+=len(arr)
                        if palette[codes].tobytes()[:len(ref)]!=ref:raise ValueError("Widget reconstruction failed")
                        packed=handle+zlib.compress(codes.tobytes(),9)
                        mapping[k]=(put(packed),len(packed)|(1<<30),k[2],k[3])
        for k in keys:
            if k not in mapping:mapping[k]=original(k)
        tables[i]=record.sub(lambda m:"{"+",".join(map(str,mapping[tuple(map(int,m.groups()))]))+"}",line)
    return result
