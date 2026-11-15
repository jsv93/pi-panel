"""Home capture must ignore repeating playback motion and preserve every pose."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'esphome/study'))
from app.db import DEFAULT_TEMPLATE
import home_zoom
from render import fixture_page


def main():
    config = copy.deepcopy(DEFAULT_TEMPLATE)
    config.update(room_label='Test room',
        lights=[dict(entity_id='light.test', name='Test lamp', soft=30, bright=100, include_presets=True)],
        media=dict(default_speaker='media_player.test', default_speaker_name='Test speaker',
                   speakers=[dict(entity_id='media_player.test', name='Test speaker')]))
    config['display'].update(theme='architectural', palette='linen', screen_width=720, screen_height=1280)
    states = [dict(entity_id='media_player.test', state='playing',
                   attributes=dict(media_title='Test track', friendly_name='Test speaker', volume_level=.2)),
              dict(entity_id='light.test', state='on', attributes=dict(brightness=255))]
    with fixture_page(config, states) as page:
        assert page.evaluate('document.getAnimations().some(a=>!Number.isFinite(a.effect.getComputedTiming().endTime))'), 'Fixture must exercise repeating playback bars'
    with tempfile.TemporaryDirectory() as temporary, patch.object(home_zoom, 'PALETTES', ('linen',)):
        root = Path(temporary)
        (root / 'linen').mkdir()
        (root / 'linen/config.json').write_text(json.dumps({'config': config}))
        home_zoom.capture(root, states, root / 'playing')
        states[0]['state'] = 'idle'
        home_zoom.capture(root, states, root / 'idle')
        playing = json.loads((root / 'playing/home_zoom.json').read_bytes())
        idle = json.loads((root / 'idle/home_zoom.json').read_bytes())
        assert len(playing['poses']) == 10
        assert playing['poses'] == idle['poses'], 'Playback must not change Home zoom timing or geometry'
        assert playing['sha256'] == idle['sha256'], 'Live player must not be baked into Home artwork'
    print('PASS active playback Home capture; identical artwork and all ten motion poses')


if __name__ == '__main__':
    main()
