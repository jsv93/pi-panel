"""Verify provider image scope, paired authorization, alpha and payload bounds."""
import asyncio
import io
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zlib

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))


async def run(main, db, artwork):
    source = io.BytesIO()
    Image.new("RGBA", (240, 120), (40, 100, 200, 128)).save(source, "PNG")
    encoded = artwork.encode(source.getvalue())
    assert encoded[:4] == b"P4RA"
    pixels = zlib.decompress(encoded[4:])
    assert len(pixels) == 96 * 96 * 4 and pixels[3::4] == bytes([128]) * (96 * 96)
    for channel, expected in enumerate((40, 100, 200)):
        assert all(abs(value - expected) <= 2 for value in pixels[channel::4])
    assert not artwork.valid("../camera", "logo.png")
    assert not artwork.valid("camera", "logo.png?token=other")
    assert artwork.valid("ai_task", "dark_icon@2x.png")

    def upstream(request):
        assert str(request.url) == "http://supervisor/core/api/brands/integration/ai_task/logo.png"
        assert request.headers["Authorization"] == "Bearer upstream-only"
        assert "X-Panel-Token" not in request.headers
        return httpx.Response(200, content=source.getvalue())

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    with patch.object(artwork.ha, "url", return_value="http://supervisor/core"), \
         patch.object(artwork.ha, "token", return_value="upstream-only"), \
         patch.object(artwork.httpx, "AsyncClient", return_value=client):
        assert await artwork.image("ai_task", "logo.png") == encoded

    db.init()
    pid, key = "study-p4", "P" * 48
    db.upsert_panel(pid, pid, "aa:bb:cc:dd:ee:ff", "192.0.2.1", "esp", "test")
    assert db.claim_panel_token(pid, key, "S" * 48, "test")
    path = f"/api/panel/{pid}/artwork/ai_task/logo.png"
    auth = {"X-Panel-Token": key}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as c:
        assert (await c.get(path)).status_code == 401
        assert (await c.get(path.replace(pid, "other"), headers=auth)).status_code == 401
        assert (await c.get(path, headers=auth)).status_code == 403
        db.claim(pid, "study", "default", "Study")
        with patch.object(main.ha, "configured", return_value=True), \
             patch.object(artwork, "image", return_value=encoded):
            response = await c.get(path, headers=auth)
            assert response.status_code == 200 and response.content == encoded
            assert (await c.get(path.replace("logo.png", "credentials"), headers=auth)).status_code == 400
            main.P4_ARTWORK_ACTIVE.add(pid)
            assert (await c.get(path, headers=auth)).status_code == 409
            main.P4_ARTWORK_ACTIVE.clear()
        with patch.object(main.ha, "configured", return_value=True), \
             patch.object(artwork, "image", side_effect=ValueError("bad image")):
            assert (await c.get(path, headers=auth)).status_code == 502
            assert not main.P4_ARTWORK_ACTIVE


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        os.environ.update(PANEL_DB=str(Path(temp) / "test.db"), ADMIN_PASSWORD="bench-only")
        from app import main, db, p4_artwork
        asyncio.run(run(main, db, p4_artwork))
        print("PASS paired provider images, fixed HA scope, alpha and request cleanup")
