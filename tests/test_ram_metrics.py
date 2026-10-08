"""Read RAM without a subprocess; carry the numeric sample through a heartbeat."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    os.environ['PANEL_DIR'] = str(root / 'panel')
    os.environ['PANEL_DB'] = str(root / 'server.db')
    os.environ['ADMIN_PASSWORD'] = 'test-only-password'
    (root / 'panel').mkdir()
    spec = importlib.util.spec_from_file_location('ram_agent', ROOT / 'agent' / 'panel-agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    agent.MEMINFO = root / 'meminfo'
    sample = 'MemTotal: 1048576 kB\nMemFree: 4096 kB\nMemAvailable: 589824 kB\nCached: 524288 kB\n'
    agent.MEMINFO.write_text(sample)
    expected = {'ram_used_mb': 448, 'ram_total_mb': 1024, 'ram_used_pct': 43.8}
    assert agent.memory_usage() == expected, 'reclaimable cache should not inflate usage'
    with patch.object(agent, 'kiosk_gpu', return_value={}), patch.object(agent, 'backlight_state', return_value={}), patch.object(agent, 'disk_writes', return_value={}):
        metrics = agent.metrics()
    assert all(metrics[key] == value for key, value in expected.items())
    for available, pct in [(0, 100.0), (1048576, 0.0)]:
        agent.MEMINFO.write_text(f'MemTotal: 1048576 kB\nMemAvailable: {available} kB\n')
        assert agent.memory_usage()['ram_used_pct'] == pct
    for invalid in ['', 'MemTotal: 0 kB\nMemAvailable: 0 kB', 'MemTotal: 1024 kB',
                    'MemTotal: bad kB\nMemAvailable: 1 kB', 'MemTotal: 1024 MB\nMemAvailable: 1 kB',
                    'MemTotal: 1024 kB\nMemAvailable: -1 kB', 'MemTotal: 1024 kB\nMemAvailable: 2048 kB']:
        agent.MEMINFO.write_text(invalid)
        assert agent.memory_usage() == {}
    agent.MEMINFO.unlink()
    assert agent.memory_usage() == {}
    with patch.object(agent, 'kiosk_gpu', return_value={}), patch.object(agent, 'backlight_state', return_value={}), patch.object(agent, 'disk_writes', return_value={}):
        assert 'ui_version' in agent.metrics(), 'missing RAM data must not stop the heartbeat'
    print('PASS agent RAM: available-memory calculation, boundaries, bad/missing input and metrics integration')

    sys.path.insert(0, str(ROOT / 'server'))
    from app.main import app
    with TestClient(app) as client:
        client.post('/api/register', json={'panel_id': 'ram-test', 'hostname': 'ram-test'})
        assert client.post('/api/heartbeat', json={'panel_id': 'ram-test', 'metrics': metrics}).status_code == 200
        client.post('/api/login', json={'password': 'test-only-password'})
        saved = client.get('/api/panels/ram-test').json()['panel']['metrics']
        assert all(saved[key] == value for key, value in expected.items())
    print('PASS RAM metrics survive heartbeat validation, persistence and admin retrieval')
