"""Reconstruct native USB-bench framebuffer captures and compare their CRCs."""
import argparse
import base64
import json
from pathlib import Path
import re
import zlib

import numpy as np
from PIL import Image


def extract(build,log,destination):
    views=json.loads((build/"screens.json").read_text())["views"]
    archive=(build/"screens.bin").read_bytes()
    frames=[bytearray(zlib.decompress(archive[v["offset"]:v["offset"]+v["size"]])) for v in views]
    complete=set()
    destination.mkdir(exist_ok=True,parents=True)
    for line in log.read_text(encoding="utf-8").splitlines():
        patch=re.search(r"QA_PIX (\d+) (\d+) ([A-Za-z0-9+/=]+)$",line)
        if patch:
            index=int(patch[1]);start=2*int(patch[2]);content=base64.b64decode(patch[3],validate=True)
            if index in complete or start+len(content)>len(frames[index]) or len(content)%2:
                raise ValueError("Invalid framebuffer patch")
            frames[index][start:start+len(content)]=content
        end=re.search(r"QA_FRAME (\d+) ([0-9a-f]{8})$",line)
        if not end:continue
        index=int(end[1]);view=views[index];raw=frames[index]
        if index in complete or zlib.crc32(raw)!=int(end[2],16):
            raise ValueError(f"USB capture failed CRC for {view['name']}")
        complete.add(index)
        pixels=np.frombuffer(raw,dtype="<u2").reshape(view["h"],view["w"]).astype(np.uint32)
        rgb=np.stack(((pixels>>11)*255/31,((pixels>>5)&63)*255/63,(pixels&31)*255/31),axis=-1)
        Image.fromarray(np.rint(rgb).astype(np.uint8)).save(destination/(view["name"]+".png"))
    if len(complete)!=len(views):
        raise ValueError(f"Received {len(complete)} of {len(views)} full frames")
    print(f"Verified {len(complete)} physical P4 framebuffer CRCs")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("build","log","destination"):parser.add_argument(name,type=Path)
    args=parser.parse_args()
    extract(args.build,args.log,args.destination)
