"""Native geometry and motion index for firmware using immutable SD artwork."""
import json
import re
import zlib
import numpy as np
from page_motion import W,H,routes,pose


def generate(directory):
    metadata=json.loads((directory/'screens.json').read_text())
    views=metadata['views'];paths=routes(views)
    encoded=(directory/'screens.bin').read_bytes()
    def pixels(view):
        return np.frombuffer(zlib.decompress(encoded[view['offset']:view['offset']+view['size']]),'<u2').reshape(view['h'],view['w'])
    scenes=pixels(next(v for v in views if v['name']=='scenes'))
    scene_changes=np.logical_or.reduce([pixels(v)!=scenes for v in metadata['scene_sprites']])
    lamps=np.zeros((H,W),dtype=bool)
    for index,name in enumerate(('reading','slider')):
        area=metadata.get('slider_paint',metadata[name]) if name=='slider' else metadata[name]
        x,y,w,h=(area[k] for k in ('x','y','width','height'))
        reference=pixels(metadata['patches'][0][index])
        mask=np.logical_or.reduce([pixels(p[index])!=reference for p in metadata['patches']])
        for view in views:
            if re.fullmatch(r'light\d+',view['name']):mask|=pixels(view)[y:y+h,x:x+w]!=reference
        lamps[y:y+h,x:x+w]=mask
    lines=['#pragma once','#include <cstdint>',
        '#ifndef STUDY_SD_ONLY\n#error This artwork index requires the card-only firmware build\n#endif',
        'namespace study {',
        'struct Block {uint32_t offset,size,bytes;};struct PathMotion {int from,to,travel;Block phases[10];};',
        'constexpr PathMotion nav_paths[]={'+','.join('{%d,%d,%d,{}}'%p for p in paths)+'};',
        'constexpr uint8_t motion_tag[]={0};',
        '#define STUDY_PACKED_SEGMENTS\n#define STUDY_PLANAR_MAPS',
        'constexpr size_t checkpoint_bytes=0,motion_bytes=0,offsets_bytes=0,header_bytes=0,entropy_bytes=0,max_frame=0;',
        'struct Pose {int shift;unsigned alpha;};constexpr Pose nav_pose[3][11]={'+
            ','.join('{'+','.join('{%d,%d}'%pose(i,t) for i in range(11))+'}' for t in (14,24,-24))+'};',
        'constexpr const char *page_names[]={'+','.join(json.dumps(v['name']) for v in views)+'};']
    for name,mask in (('scene',scene_changes),('lamp',lamps)):
        tiles=mask.reshape(H//8,8,W//16,16).any(axis=(1,3))
        lines.append('constexpr uint8_t '+name+'_changes[]={'+','.join(map(str,np.packbits(tiles.ravel(),bitorder='little')))+'};')
    (directory/'navigation_assets.h').write_text('\n'.join(lines+['}'])+'\n',encoding='ascii')
    (directory/'motion_chunks.h').write_text('#pragma once\nnamespace study {\nconstexpr unsigned chunk_count=0,chunk_bytes=0;\nstruct ChunkBlock {uint32_t offset,size;};constexpr ChunkBlock chunk_recipes[]={{0,0}},chunk_maps[]={{0,0}};\nconstexpr char chunk_data[]="\\x00";\n}\n',encoding='ascii')
    # These compatibility placeholders give prepare.py a deterministic layout
    # without generating or ever provisioning the obsolete shared flash bank.
    (directory/'study-motion.bin').write_bytes(bytes(32))
    (directory/'jpeg_meta.json').write_text(json.dumps([0,0,0,[[*p,[[0,0]]*10] for p in paths]]))
