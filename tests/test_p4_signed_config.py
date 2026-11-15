"""Exercise the embedded representation against the real server and SQLite store."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
from fastapi.testclient import TestClient

def main():
    with tempfile.TemporaryDirectory() as temp:
        os.environ["PANEL_DB"]=str(Path(temp)/"panels.db")
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
        from app import main as server, db
        token,key="t"*40,"s"*40
        accept={"Accept":"application/vnd.pi-panel.config+json"}
        with TestClient(server.app) as client:
            assert client.post("/api/register",json={"panel_id":"other"}).is_success
            assert client.get("/api/config/other",headers=accept).status_code==403
            assert client.post("/api/register",json={"panel_id":"p4","kind":"esp"},
                headers={"X-Panel-Token":token,"X-Panel-Sign-Key":key}).is_success
            db.claim("p4","study","default","Étude")
            assert client.get("/api/config/p4",headers=accept).status_code==401
            headers={"X-Panel-Token":token}
            legacy=client.get("/api/config/p4",headers=headers).json()
            signed=client.get("/api/config/p4",headers={**headers,**accept})
            assert signed.is_success
            signature=hmac.new(key.encode(),signed.content,hashlib.sha256).hexdigest()
            assert signed.headers["X-Panel-Signature"]==legacy.pop("_sig")==signature
            assert signed.json()==legacy and signed.json()["_panel_id"]=="p4"
            assert signed.content==json.dumps(legacy,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode()
            assert signed.headers["cache-control"]=="no-store"
            assert not hmac.compare_digest(signature,hmac.new(token.encode(),signed.content,hashlib.sha256).hexdigest())
            config=db.merged_config('p4')
            config['lights']=[dict(entity_id='light.test',name='Test',soft=30,bright=100,include_presets=True)]
            config['display'].update(touch_gesture='lights',touch_points=4,touch_hold_ms=600)
            db.save_config('p4',config)
            edit=client.post('/api/panel/p4/light',headers=headers,
                             json={'entity_id':'light.test','include_presets':False})
            assert edit.is_success,edit.text
            updated=client.get('/api/config/p4',headers={**headers,**accept})
            assert updated.json()['_version']==edit.json()['version']
            assert updated.json()['display']['touch_points']==4
            assert updated.json()['lights'][0]['include_presets'] is False
            assert updated.headers['X-Panel-Signature']==hmac.new(key.encode(),updated.content,hashlib.sha256).hexdigest()
            print("PASS authenticated canonical bytes, signature, device identity, UTF-8 room and legacy CM5 response")

if __name__=="__main__":main()
