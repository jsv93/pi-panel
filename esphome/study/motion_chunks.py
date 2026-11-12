"""Prepare the most frequently reused eight-MCU runs without enlarging the asset partition."""
import json
from pathlib import Path
import zlib
import numpy as np

def emit(d: Path):
    prefix,entropy,_,paths=json.loads((d/"jpeg_meta.json").read_text())
    maps=(d/"jpeg_bank.bin").read_bytes()[prefix+entropy:]
    lengths=np.diff(np.fromfile(d/"jpeg_offsets.bin",dtype="<u4"))
    ids=np.stack([np.frombuffer(zlib.decompress(maps[o:o+s]),"<u4")
                  for _,_,_,phases in paths for o,s in phases])
    groups=ids.reshape(-1,8).view(np.dtype((np.void,32))).ravel()
    keys,inverse,counts=np.unique(groups,return_inverse=True,return_counts=True)
    groups=keys.view("<u4").reshape(-1,8)
    sizes=lengths[groups].sum(axis=1)+16
    ranked=np.argsort(-counts.astype(float)/sizes)
    selected=ranked[np.cumsum(sizes[ranked])<=4*1024*1024]
    codes=np.zeros(len(keys),dtype="<u2")
    codes[selected]=np.arange(1,len(selected)+1)
    indices=codes[inverse].reshape(len(ids),-1)
    blob=bytearray()
    def store(raw):
        packed=zlib.compress(raw,6);result="{%d,%d}"%(len(blob),len(packed))
        blob.extend(packed)
        return result
    recipes=[store(groups[selected[i:i+128]].tobytes()) for i in range(0,len(selected),128)]
    lookups=[store(row.tobytes()) for row in indices]
    with (d/"motion_chunks.h").open("w",encoding="ascii") as h:
        h.write("#pragma once\nnamespace study {\nconstexpr unsigned chunk_count=%d, chunk_bytes=%d;\n"%(len(selected),sizes[selected].sum()))
        h.write("struct ChunkBlock {uint32_t offset,size;};\nconstexpr ChunkBlock chunk_recipes[]={"+",".join(recipes)+"};\n")
        h.write("constexpr ChunkBlock chunk_maps[]={"+",".join(lookups)+"};\n")
        h.write("static const unsigned char chunk_data[]=\n")
        for i in range(0,len(blob),512):
            h.write('"'+''.join('\\x%02x'%v for v in blob[i:i+512])+'"\n')
        h.write("; }\n")
    print(f"{len(selected)} reusable runs cover {counts[selected].sum()/len(inverse):.1%} of the frame assembly operations")
