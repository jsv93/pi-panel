"""Exercise the paired HTTP ring and bounded JPEG stream using the real API."""
import asyncio
import io
import os
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"server"))


async def run(main,db,video):
    pid="study-p4"
    key="P"*48
    db.init()
    db.upsert_panel(pid,pid,"aa:bb:cc:dd:ee:ff","192.0.2.1","esp","test")
    assert db.claim_panel_token(pid,key,"S"*48,"test")
    db.claim(pid,"study","default","Study")
    cfg=db.merged_config(pid)
    cfg["doorbell"]={"enabled":True,"camera":"camera.study","duration_s":30}
    db.save_config(pid,cfg)
    img=Image.new("RGB",(320,240),"orange");encoded=io.BytesIO();img.save(encoded,"JPEG")
    jpg=encoded.getvalue()
    body=b"--abc\r\nContent-Type: image/jpeg\r\n\r\n"+jpg+b"\r\n--abc--\r\n"
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(0,len(body),13):yield body[i:i+13]
    for boundary in ("abc","--abc"):
        response=httpx.Response(200,headers={"Content-Type":f"multipart/x-mixed-replace; boundary={boundary}"},stream=Chunks())
        assert [part async for part in video.jpeg_parts(response)]==[jpg]
    data=video.encode(jpg)
    assert Image.open(io.BytesIO(data)).size==(640,400)
    seen=[]
    async def source(eid):
        seen.append(eid);yield struct.pack(">I",len(data))+data
    path=f"/api/panel/{pid}/doorbell/"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://localhost") as c:
        auth={"X-Panel-Token":key}
        assert (await c.get(path+"video")).status_code==401
        assert (await c.get("/api/panel/other/doorbell/video",headers=auth)).status_code==401
        wait=asyncio.create_task(c.get(path+"wait",headers=auth))
        for _ in range(50):
            if pid in main.P4_BELL_WAITERS:break
            await asyncio.sleep(.01)
        assert (await c.get(path+"wait",headers=auth)).status_code==409
        assert (await c.post(f"/api/panels/{pid}/doorbell/test")).status_code==401
        assert (await c.post("/api/login",json={"password":os.environ["ADMIN_PASSWORD"]})).is_success
        with patch.object(main.ha,"configured",return_value=True),patch.object(video,"video",source):
            assert (await c.post(f"/api/panels/{pid}/doorbell/test",headers={"X-Panel-Access":"1"})).is_success
            assert (await wait).text=="ring"
            reply=await c.get(path+"video?camera=camera.other",headers=auth)
            assert reply.is_success and reply.content==struct.pack(">I",len(data))+data
        assert seen==["camera.study"] and pid not in main.P4_VIDEO_ACTIVE and pid not in main.P4_BELL_WAITERS


if __name__=="__main__":
    with tempfile.TemporaryDirectory() as temp:
        os.environ.update(PANEL_DB=str(Path(temp)/"test.db"),ADMIN_PASSWORD="bench-only")
        from app import main,db,p4_video
        asyncio.run(run(main,db,p4_video))
        print("PASS paired stream, admin ring, camera scope, multipart boundaries and JPEG dimensions")
