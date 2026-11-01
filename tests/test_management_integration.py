"""Exercise the real routes, WebSocket dispatcher, signing and ingress mount."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


def run(root):
    os.environ.update(PANEL_DB=str(root / "panels.db"), PANEL_MANAGEMENT_POLICY=str(root / "policy.json"),
                      PANEL_MANAGEMENT_AUDIT=str(root / "audit.db"), ADMIN_PASSWORD="regression-only")
    key, token, sign = "k" * 43, "t" * 43, "s" * 43
    (root / "policy.json").write_text(json.dumps({"origin": "https://panels.example", "users": {
        "operator": {"key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                     "roles": ["diagnostics.read"], "panels": ["study"]}}}))
    from app import main
    outer = FastAPI()
    prefix = "/api/hassio_ingress/testtoken"
    outer.mount(prefix, main.app)
    with TestClient(outer, base_url="https://panels.example") as c:
        headers = {"Origin": "https://panels.example"}
        r = c.post(prefix + "/api/register", json={"panel_id": "study", "hostname": "study", "kind": "pi"},
                   headers={"X-Panel-Token": token, "X-Panel-Sign-Key": sign})
        assert r.status_code == 200, r.text
        r = c.post(prefix + "/management/api/session", headers=headers,
                   json={"user": "operator", "key": key, "panel": "study"})
        assert r.status_code == 200, r.text
        headers["Authorization"] = "Bearer " + r.json()["session"]
        with c.websocket_connect("wss://panels.example" + prefix + "/api/ws/study",
                                 headers={"X-Panel-Token": token}) as ws:
            assert ws.receive_json()["type"] == "hello"
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(c.post, prefix + "/management/api/panels/study/diagnostic",
                                     headers=headers, json={"operation": "health"})
                request = ws.receive_json()
                signature = request.pop("_sig")
                expected = hmac.new(sign.encode(), json.dumps(request, sort_keys=True, separators=(",", ":"),
                                                             ensure_ascii=True).encode(), hashlib.sha256).hexdigest()
                assert hmac.compare_digest(signature, expected)
                assert request["capture"] is False
                ws.send_json({"type": "screen_diagnostics", "request_id": request["request_id"],
                              "metrics": {"cpu_temp": 64, "secret": "must-not-leak"}})
                result = future.result(timeout=12)
                assert result.status_code == 200, result.text
                assert result.json()["metrics"] == {"cpu_temp": 64}
            # Ordinary config-channel heartbeats still function after diagnostics.
            ws.send_json({"type": "heartbeat", "metrics": {"cpu_temp": 64}})
            assert ws.receive_json()["type"] == "ack"
        page = c.get(prefix + "/management/")
        assert page.status_code == 200
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert "sha256-" not in page.headers["content-security-policy"]
        assert c.get(prefix + "/management/console.js").status_code == 200
        dashboard = c.get(prefix + "/")
        assert dashboard.status_code == 200
        assert "sha256-" in dashboard.headers["content-security-policy"]
        assert c.post(prefix + "/api/login", json={"password": "regression-only"}).status_code == 200
        assert c.get(prefix + "/api/panels").status_code == 200
        assert c.post(prefix + "/management/api/logout", headers=headers).status_code == 200
        assert c.post(prefix + "/management/api/panels/study/diagnostic", headers=headers,
                      json={"operation": "health"}).status_code == 401
    print("PASS real dispatcher, signed diagnostic, WSS routing, heartbeat, ingress assets, separate CSP, dashboard login, logout")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as folder:
        run(Path(folder))
