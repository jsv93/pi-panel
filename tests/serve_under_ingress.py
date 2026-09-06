"""Serve the config server the way Home Assistant does: mounted under an
ingress path rather than at the root.

The export bug was invisible at the root, because an absolute /api/... path
happens to be correct there. It is only wrong once the app lives under a prefix,
which is how it actually runs.
"""
import os
import sys

sys.path.insert(0, os.environ["PANEL_SERVER_DIR"])

from fastapi import FastAPI
from app.main import app as inner

PREFIX = "/api/hassio_ingress/testtoken"

outer = FastAPI()
outer.mount(PREFIX, inner)


@outer.get("/")
async def root():
    return {"hint": "the add-on is mounted at " + PREFIX}
