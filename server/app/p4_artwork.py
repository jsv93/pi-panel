"""Bounded Home Assistant provider artwork for enrolled P4 panels."""
import asyncio
import io
import re
import zlib

import httpx
from PIL import Image, ImageOps

from . import ha

SIDE = 96
MAX_SOURCE = 1_000_000
MAX_PACKET = 16_384
IMAGES = {f"{dark}{kind}{scale}.png" for dark in ("", "dark_")
          for kind in ("icon", "logo") for scale in ("", "@2x")}


def valid(domain, image):
    return bool(re.fullmatch(r"[a-z0-9_]{1,100}", domain)) and image in IMAGES


def encode(data):
    with Image.open(io.BytesIO(data)) as source:
        if source.format != "PNG" or source.width * source.height > 4_000_000:
            raise ValueError("Unsupported provider artwork")
        rgba = ImageOps.fit(source.convert("RGBA"), (SIDE, SIDE), Image.Resampling.LANCZOS)
        packet = b"P4RA" + zlib.compress(rgba.tobytes(), 9)
    if len(packet) > MAX_PACKET:
        raise ValueError("Provider artwork exceeds the cache limit")
    return packet


async def image(domain, name):
    if not valid(domain, name):
        raise ValueError("Invalid provider artwork path")
    url = f"{ha.url()}/api/brands/integration/{domain}/{name}"
    headers = {"Authorization": f"Bearer {ha.token()}"}
    async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            data = bytearray()
            async for block in response.aiter_bytes(16384):
                if len(data) + len(block) > MAX_SOURCE:
                    raise ValueError("Provider artwork exceeds the input limit")
                data.extend(block)
    return await asyncio.to_thread(encode, data)
