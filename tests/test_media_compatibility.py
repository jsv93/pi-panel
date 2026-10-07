"""Speaker capability is distinct from playback state and native entity names."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as scratch:
    os.environ['PANEL_DB'] = str(Path(scratch) / 'panels.db')
    os.environ['ADMIN_PASSWORD'] = 'test-only-password'
    sys.path.insert(0, str(ROOT / 'server'))
    from app.main import app
    from app import ha

    def player(name, state='idle', mass=False):
        return {'entity_id': 'media_player.'+name, 'state': state,
                'attributes': {'friendly_name': name, **({'mass_player_type': 'player'} if mass else {})}}

    samples = [player('lamp_sonos'), player('lamp_ma', mass=True),
               player('offline', 'unavailable', True), player('external', 'playing')]
    with TestClient(app) as client, patch.object(ha, 'states', AsyncMock(return_value=samples)):
        assert client.get('/api/entities?domain=media_player').status_code == 401
        client.post('/api/login', json={'password': 'test-only-password'})
        for service, expected in [(True, 'supported'), (False, 'unsupported'), (None, 'unknown')]:
            with patch.object(ha, 'transfer_service_available', AsyncMock(return_value=service)):
                entities = {e['entity_id']: e for e in client.get('/api/entities?domain=media_player').json()}
            assert entities['media_player.lamp_ma']['queue_transfer'] == expected
            assert entities['media_player.lamp_sonos']['queue_transfer'] == 'unsupported'
            assert entities['media_player.offline']['queue_transfer'] == 'unavailable'
            assert entities['media_player.external']['queue_transfer'] == 'unsupported'
        with patch.object(ha, 'transfer_service_available', AsyncMock()) as services:
            client.get('/api/entities?domain=light')
            services.assert_not_called()
    print('PASS entity compatibility: idle MA supported, native control-only, offline, missing service, unknown service and auth')

    import asyncio
    async def check_services():
        real_client = httpx.AsyncClient
        calls = []
        def respond(request):
            calls.append(request.url.path)
            return httpx.Response(200, json=[{'domain': 'music_assistant', 'services': {'transfer_queue': {}}}])
        with patch.object(ha, 'configured', return_value=True), patch.object(ha, 'url', return_value='http://ha.test'), patch.object(ha, 'token', return_value='test-only'):
            with patch.object(ha.httpx, 'AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs)):
                ha.invalidate()
                assert await ha.transfer_service_available() is True
                assert await ha.transfer_service_available() is True
                assert calls == ['/api/services']
                ha.invalidate()
                assert await ha.transfer_service_available() is True
                assert len(calls) == 2
            ha.invalidate()
            with patch.object(ha.httpx, 'AsyncClient', side_effect=httpx.ConnectError('offline')):
                assert await ha.transfer_service_available() is None
    asyncio.run(check_services())
    print('PASS service discovery caches results, invalidates correctly and reports connection failures as unknown')
