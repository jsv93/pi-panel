"""Build a lossless span map for transitions between Lights and the first lamp."""
import zlib
import numpy as np
from PIL import Image, ImageChops

def lamp_regions(manifest, artwork):
    views={p["name"]:p for p in manifest["views"]}
    def pixels(sprite):
        start=sprite["offset"]
        raw=zlib.decompress(artwork[start:start+sprite["size"]])
        return Image.frombytes("RGB",(sprite["w"],sprite["h"]),raw,"raw","BGR;16")
    base=pixels(views["lights"])
    lamp=pixels(views["light0"])
    variations=Image.new("RGB",base.size)
    for i,key in enumerate(("reading","slider")):
        reference=pixels(manifest["patches"][0][i])
        rect=manifest.get("slider_paint",manifest["slider"]) if key=="slider" else manifest[key]
        x,y=rect["x"],rect["y"]
        changes=ImageChops.difference(reference,lamp.crop((x,y,x+reference.width,y+reference.height)))
        for patch in manifest["patches"]:
            changes=ImageChops.lighter(changes,ImageChops.difference(reference,pixels(patch[i])))
        variations.paste(changes,(rect["x"],rect["y"]))
    # The solid lamp-sheet background is now represented by a screen-anchored
    # ordered dither. Its left gutter supplies one complete four-pixel period
    # for each row. Keep that shared background still while the controls move.
    base_rgb=np.asarray(base)
    gutter=np.tile(base_rgb[:,:4],(1,base.width//4,1))
    base_is_gutter=(base_rgb==gutter).all(axis=2)
    changed=np.zeros(base_is_gutter.shape,dtype=bool)
    variation=np.asarray(variations).any(axis=2)
    for offset in range(15):
        width=base.width-offset
        for picture in (base,lamp):
            incoming=np.asarray(picture)[:,:width]
            differs=(incoming!=base_rgb[:,offset:]).any(axis=2)
            steady=base_is_gutter[:,offset:] & (incoming==gutter[:,:width]).all(axis=2)
            changed[:,offset:] |= differs & ~steady
        changed[:,offset:] |= variation[:,:width]
    changed=Image.fromarray(changed)
    # Align spans to eight pixels for RAM copies, and retain gaps between glyphs.
    spans=[]
    for y in range(1280):
        row=changed.crop((0,y,720,y+1))
        boxes=[]
        for x in range(0,720,16):
            if row.crop((x,0,x+16,1)).getbbox():
                if boxes and boxes[-1][1]+16>=x:boxes[-1][1]=x+16
                else:boxes.append([x,x+16])
        spans.extend((left,y,right-left) for left,right in boxes)
    return spans
