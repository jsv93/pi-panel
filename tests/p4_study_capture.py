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


def extract_live(build, log, destination):
    names = json.loads((build / "live_views.json").read_text())
    views = json.loads((build / "screens.json").read_text())["views"]
    width, height = views[0]["w"], views[0]["h"]
    frame_size = width * height * 2
    done = []
    active = None
    data = bytearray()
    destination.mkdir(parents=True, exist_ok=True)
    with log.open(encoding="utf-8") as stream:
        for line in stream:
            start = re.search(r"LIVE_BEGIN ([\w-]+) (\d+) ([0-9a-f]{8}) (raw|delta) (\d+)$", line)
            if start:
                if active is not None or len(done) == len(names):
                    raise ValueError("Unexpected or overlapping capture")
                active, size, crc = start[1], int(start[2]), int(start[3], 16)
                encoding = start[4]
                base = int(start[5])
                if active != names[len(done)] or not 0 < size <= frame_size:
                    raise ValueError("Unexpected live capture header")
                data.clear()
            chunk = re.search(r"LIVE_PIX (\d+) ([A-Za-z0-9+/=]+)$", line)
            if chunk:
                if not active or int(chunk[1]) != len(data):
                    raise ValueError(f"Missing or misplaced USB data on {active}, expected {len(data)}, received {chunk[1]}")
                data.extend(base64.b64decode(chunk[2], validate=True))
                if len(data) > size:
                    raise ValueError("USB capture exceeded declared size")
            end = re.search(r"LIVE_END ([\w-]+)$", line)
            if end:
                if end[1] != active or len(data) != size:
                    raise ValueError("Incomplete capture")
                if encoding == "delta":
                    raw = bytearray()
                    offset = 0
                    while offset + 2 <= size:
                        control = int.from_bytes(data[offset:offset+2], "little")
                        offset += 2
                        count = (control & 32767) + 1
                        span = 2 if control & 32768 else 2*count
                        if offset+span > size or len(raw)+count*2 > frame_size:
                            raise ValueError("Invalid RGB565 span")
                        block = data[offset:offset+span]
                        raw.extend(block * (count if control & 32768 else 1))
                        offset += span
                    if offset != size:
                        raise ValueError("Partial RGB565 span")
                    if base >= len(views) or len(raw) != frame_size:
                        raise ValueError("Invalid reference page")
                    ref = views[base]
                    with (build / "screens.bin").open("rb") as archive:
                        archive.seek(ref["offset"])
                        original = zlib.decompress(archive.read(ref["size"]))
                    raw = np.bitwise_xor(np.frombuffer(original,dtype=np.uint8),np.frombuffer(raw,dtype=np.uint8)).tobytes()
                else:
                    raw = data
                if len(raw) != frame_size or zlib.crc32(raw) != crc:
                    raise ValueError(f"Live framebuffer did not verify for {active}")
                rgb565 = np.frombuffer(raw, dtype="<u2").reshape(height, width).astype(np.uint32)
                rgb = np.stack(((rgb565 >> 11)*255/31, ((rgb565 >> 5)&63)*255/63, (rgb565&31)*255/31), axis=-1)
                Image.fromarray(np.rint(rgb).astype(np.uint8)).save(destination / (active + ".png"))
                done.append(active)
                active = None
    if done != names:
        raise ValueError(f"Verified {len(done)} of {len(names)} live screens")
    print(f"Verified {len(done)} live framebuffer CRCs")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true")
    for name in ("build","log","destination"):parser.add_argument(name,type=Path)
    args=parser.parse_args()
    (extract_live if args.live else extract)(args.build,args.log,args.destination)
