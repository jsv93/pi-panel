"""Transcode one configured Home Assistant MJPEG camera for a paired Study P4."""
import asyncio
import io
import struct
import time
from email.message import Message

import httpx
from PIL import Image

from . import ha

MAX_PART = 4_000_000
MAX_JPEG = 45_000


def encode(jpeg):
    with Image.open(io.BytesIO(jpeg)) as source:
        if source.format != "JPEG" or source.width * source.height > 12_000_000:
            raise ValueError("Unsupported camera image")
        source.draft("RGB", (1280, 800))
        frame = source.convert("RGB")
        frame.thumbnail((640, 1024),Image.Resampling.LANCZOS)
    for edge in (1024,640,400):
        frame.thumbnail((edge,edge),Image.Resampling.LANCZOS)
        for quality in (86, 72, 56, 40, 25):
            target = io.BytesIO()
            frame.save(target, "JPEG", quality=quality, subsampling=2)
            if target.tell() <= MAX_JPEG:
                return target.getvalue()
    raise ValueError("Camera image exceeds decoder capacity")


async def jpeg_parts(response):
    mime = Message()
    mime["Content-Type"] = response.headers.get("Content-Type", "")
    boundary = mime.get_boundary()
    if mime.get_content_type() != "multipart/x-mixed-replace" or not boundary or len(boundary)>128:
        raise ValueError("Camera did not return multipart video")
    declared=boundary.encode("ascii")
    marker = b"--" + declared
    buffer = bytearray()
    first=True
    async for chunk in response.aiter_bytes(32768):
        buffer.extend(chunk)
        while True:
            if first:
                line=buffer.partition(b"\r\n")[0]
                if line==declared and declared.startswith(b"--"):
                    marker=declared
            start = buffer.find(marker)
            if start < 0:
                if len(buffer)>4096:raise ValueError("Invalid camera multipart preamble")
                break
            if start:del buffer[:start]
            first=False
            if buffer[len(marker):len(marker)+2] == b"--":return
            headers = buffer.find(b"\r\n\r\n",len(marker))
            if headers < 0:
                if len(buffer)>8192:raise ValueError("Oversized camera headers")
                break
            if headers>8192:raise ValueError("Oversized camera headers")
            end = buffer.find(b"\r\n"+marker,headers+4)
            if end < 0:
                if len(buffer)>MAX_PART+8192:raise ValueError("Oversized camera part")
                break
            if end-headers-4>MAX_PART:raise ValueError("Oversized camera part")
            frame = bytes(buffer[headers+4:end])
            del buffer[:end+2]
            if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
                raise ValueError("Invalid JPEG camera part")
            yield frame


def video(camera):
    return frames_from_url(f"{ha.url()}/api/camera_proxy_stream/{camera}",
                           {"Authorization":f"Bearer {ha.token()}"})


async def frames_from_url(url,headers):
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False) as client:
        async with client.stream("GET",url,headers=headers) as response:
            response.raise_for_status()
            last = 0.0
            async for jpeg in jpeg_parts(response):
                now = time.monotonic()
                if now-last<1/24:continue
                last=now
                data=await asyncio.to_thread(encode,jpeg)
                yield struct.pack(">I",len(data))+data
