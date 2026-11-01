"""Doorbell config and admin test route: no arbitrary camera/URL in a ring."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(PANEL_DB=str(Path(tmp)/'test.db'), ADMIN_PASSWORD='test-password')
    sys.path.insert(0, str(ROOT/'server'))
    from app import main, db, doorbell
    valid={'enabled':True,'camera':'camera.front','title':'Front door','duration_s':30,'trigger':'event.bell'}
    doorbell.validate(valid)
    for change in [{'camera':'https://evil.test'},{'trigger':'light.room'},{'duration_s':True},{'duration_s':121},{'enabled':'yes'},{'title':'x'*81},{'extra':'x'}]:
        try:doorbell.validate({**valid,**change})
        except ValueError:pass
        else:raise AssertionError(change)
    with TestClient(main.app) as c:
        c.post('/api/register',json={'panel_id':'p1','hostname':'p1'})
        endpoint='/api/panels/p1/doorbell/test'
        assert c.post(endpoint).status_code==401
        c.post('/api/login',json={'password':'test-password'})
        assert c.post(endpoint).status_code==403
        headers={'X-Panel-Access':'1'}
        assert c.post(endpoint,headers=headers).status_code==409
        assert c.put('/api/panels/p1/config',json={'doorbell':{**valid,'camera':'http://bad'}}).status_code==400
        assert c.put('/api/panels/p1/config',json={'doorbell':valid}).status_code==200
        assert c.post(endpoint,headers=headers).status_code==503
        with patch.dict(main.LIVE,{'p1':object()}),patch.object(main.ha,'configured',return_value=True),patch.object(main.ha,'ring_doorbell',new_callable=AsyncMock) as ring:
            assert c.post(endpoint,headers=headers,json={'camera':'camera.other','panel_id':'p2'}).status_code==200
            ring.assert_awaited_once_with('p1')
            assert c.post(endpoint,headers=headers).status_code==429
        assert c.post('/api/panels/missing/doorbell/test',headers=headers).status_code==404
    print('PASS strict settings, admin auth, CSRF header, saved per-device selection, offline check, rate limit')
