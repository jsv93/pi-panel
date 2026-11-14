"""Run in the release image under QEMU qemu64, matching legacy HA VM CPUs."""
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(os.environ.get('PANEL_P4_SOURCE',Path(__file__).resolve().parents[1]))/'esphome/study'))
from render import rgb565

assert not np._core._multiarray_umath.__cpu_features__.get('SSE4_2',False), 'Test needs the legacy CPU emulator'
for rgb,word in [((0,0,0),0),((255,255,255),65535),((255,0,0),63488),((0,255,0),2016),((0,0,255),31)]:
    pixels=np.frombuffer(rgb565(Image.new('RGB',(720,1280),rgb)),dtype='<u2')
    assert np.all(pixels==word),(rgb,np.unique(pixels))
print('PASS NumPy import and full-resolution RGB565 artwork on legacy HA virtual CPU')
