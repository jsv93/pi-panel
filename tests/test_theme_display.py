"""Theme registration and narrow display updates survive server validation."""
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as scratch:
    os.environ['PANEL_DB'] = str(Path(scratch) / 'panels.db')
    os.environ['ADMIN_PASSWORD'] = 'test-only-password'
    sys.path.insert(0, str(ROOT / 'server'))
    from app.main import app
    with TestClient(app) as client:
        assert client.post('/api/login', json={'password': 'test-only-password'}).status_code == 200
        assert client.post('/api/register', json={'panel_id': 'theme-test', 'hostname': 'theme-test'}).status_code == 200
        assert client.get('/api/panels/theme-test').json()['config']['display']['hide_nav_on_sheets'] is False
        original = {'room_label': 'Study', 'lights': [{'entity_id': 'light.test', 'soft': 30, 'bright': 80}], 'display': {'theme': 'ambient', 'palette': 'ember', 'touch_gesture': 'lights'}}
        assert client.put('/api/panels/theme-test/config', json=original).status_code == 200
        for theme, palette in [('architectural', 'linen'), ('default', 'midnight'), ('ambient', 'ember')]:
            result = client.patch('/api/panels/theme-test/display', json={'theme': theme, 'palette': palette})
            assert result.status_code == 200, result.text
            config = client.get('/api/panels/theme-test').json()['config']
            assert config['display']['theme'] == theme
            assert config['display']['palette'] == palette
            assert config['display']['touch_gesture'] == 'lights'
            assert config['lights'] == original['lights']
        assert client.patch('/api/panels/theme-test/display', json={'hide_nav_on_sheets': False}).status_code == 200
        config = client.get('/api/panels/theme-test').json()['config']
        assert config['display']['hide_nav_on_sheets'] is False
        assert config['lights'] == original['lights']
        for patch in [{'theme': 'invalid'}, {'palette': 'invalid'}, {'ha_token': 'invalid'}]:
            assert client.patch('/api/panels/theme-test/display', json=patch).status_code == 400
        gui = client.get('/').text
        assert 'value="architectural"' in gui and 'value="linen"' in gui
        assert 'Compact icons — labels on Home' in gui
        print('PASS: theme/palette accepted and persisted; unrelated config preserved; invalid display writes rejected; admin selectors present')
