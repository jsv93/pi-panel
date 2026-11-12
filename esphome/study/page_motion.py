"""Navigation routes and the native RGB565 reference compositor."""
import numpy as np

W,H=720,1280
STEPS=11

def pose(step,travel):
    lo,hi=0.,1.
    for _ in range(12):
        u=(lo+hi)/2
        if u*u*(1.74-.74*u)<step/(STEPS-1):lo=u
        else:hi=u
    u=(lo+hi)/2
    ease=u*u*(3-2*u)
    start=.35 if abs(travel)==24 else .30
    return round(travel*(1-ease)),round(32*(start+(1-start)*ease))

def routes(views):
    names=[v["name"] for v in views]
    paths=set()
    for a,v in enumerate(views):
        if v["name"] in ("idle","doorbell"):continue
        for link in v["links"]:
            if link["to"] not in names or link["to"] in ("idle","doorbell"):continue
            b=names.index(link["to"])
            if a==b:continue
            paths.add((a,b,14))
            paths.add((b,0 if link["root"] else a,14))
    for a in range(names.index("media")):
        paths.update(((a,a+1,24),(a+1,a,-24),(a+1,0,14)))
    return sorted(p for p in paths if p[0]!=p[1])

def frame(bg,fg,step,travel,clip):
    shift,a=pose(step,travel)
    if step==STEPS-1:return fg.astype("<u2")
    incoming=np.roll(fg,shift,axis=1) if shift else fg
    b=32-a
    rb=(((bg&0xf81f)*b+(incoming&0xf81f)*a)>>5)&0xf81f
    green=(((bg&0x07e0)*b+(incoming&0x07e0)*a)>>5)&0x07e0
    result=(rb|green).astype("<u2")
    if shift>0:result[:,:shift]=bg[:,:shift]
    if shift<0:result[:,shift:]=bg[:,shift:]
    result[clip:]=fg[clip:]
    return result
