"""Security boundaries and a simulated enrolled agent; no real devices used."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from app import management as m

KEY = "a" * 43
TOKEN = "t" * 43
SIGN = "s" * 43


class DB:
    token, sign, enabled = TOKEN, SIGN, True
    def get_panel(self, panel):
        return {"id": panel, "agent_version": "test", "last_seen": time.time()} if panel in ("study", "other") else None
    def get_panel_token(self, panel): return self.token
    def get_panel_sign_key(self, panel): return self.sign
    def merged_config(self, panel): return {"display": {"remote_diagnostics": self.enabled}}


class WS:
    def __init__(self, manager, scheme="wss"):
        self.url = URL(scheme + "://panels.example/api/ws/study")
        self.headers = {"x-panel-token": TOKEN}
        self.manager, self.messages = manager, []
        self.behavior = "normal"

    async def send_json(self, data):
        self.messages.append(data)
        if self.behavior == "silence": return
        reply = {"type": "screen_diagnostics", "request_id": data["request_id"],
                 "metrics": {"cpu_temp": 64, "ha_token": "do-not-return", "browser_health": "Healthy"}}
        if self.behavior == "large": reply["padding"] = "x" * 65537
        if self.behavior == "wrong_id": reply["request_id"] = "wrong"
        if self.behavior == "wrong_socket":
            self.manager.receive("study", WS(self.manager), reply)
            return
        if self.behavior == "wrong_panel":
            self.manager.receive("other", self, reply)
            return
        if self.behavior == "revoke":
            self.manager.sessions.clear()
        if self.behavior == "rotate": self.manager.db.token = "new-token"
        if self.behavior == "replace": self.manager.live["study"] = WS(self.manager)
        self.manager.receive("study", self, reply)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = self.root / "policy.json"
        self.audit = self.root / "audit.db"
        self.cfg = {"origin": "https://panels.example", "users": {"joel": {
            "key_sha256": m.digest(KEY), "roles": [m.ROLE], "panels": ["study"]}}}
        self.save_policy()
        self.env = patch.dict(os.environ, PANEL_MANAGEMENT_POLICY=str(self.policy), PANEL_MANAGEMENT_AUDIT=str(self.audit))
        self.env.start()
        self.app = FastAPI()
        self.live = {}
        self.manager = m.install(self.app, DB(), self.live, lambda p, x: {**x, "_sig": "test-signature"})
        self.ws = WS(self.manager)
        self.live["study"] = self.ws
        self.client = TestClient(self.app, base_url="https://panels.example")
        self.headers = {"Origin": "https://panels.example"}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def save_policy(self): self.policy.write_text(json.dumps(self.cfg), encoding="utf-8")
    def login(self, **overrides):
        return self.client.post("/management/api/session", headers=self.headers,
            json={"user": "joel", "key": KEY, "panel": "study", **overrides})
    def signin(self):
        r = self.login()
        self.assertEqual(r.status_code, 200, r.text)
        self.headers["Authorization"] = "Bearer " + r.json()["session"]
        return r
    def run_check(self, operation="health", panel="study", **extra):
        return self.client.post(f"/management/api/panels/{panel}/diagnostic", headers=self.headers,
                                json={"operation": operation, **extra})

    def test_disabled_by_default(self):
        with patch.dict(os.environ, PANEL_MANAGEMENT_POLICY=""):
            self.assertEqual(self.login().status_code, 503)

    def test_tls_cannot_be_faked_by_request_header(self):
        self.client.base_url = "http://panels.example"
        self.headers["X-Forwarded-Proto"] = "https"
        self.assertEqual(self.login().status_code, 403)

    def test_origin_required_and_exact(self):
        for origin in (None, "https://evil.example", "null", "https://panels.example.evil"):
            self.headers = {"Origin": origin} if origin else {}
            self.assertEqual(self.login().status_code, 403)

    def test_shared_admin_cookie_and_panel_token_are_not_operator_auth(self):
        self.headers.update(Cookie="psid=legacy-admin", **{"X-Panel-Token": TOKEN})
        self.assertEqual(self.run_check().status_code, 401)
        self.assertEqual(self.login(key="changeme").status_code, 401)

    def test_role_device_and_bad_credential_denials(self):
        self.assertEqual(self.login(key="wrong").status_code, 401)
        self.assertEqual(self.login(panel="other").status_code, 401)
        self.cfg["users"]["joel"]["roles"] = ["viewer"]
        self.save_policy()
        self.assertEqual(self.login().status_code, 401)

    def test_device_bound_session(self):
        self.signin()
        self.assertEqual(self.run_check(panel="other").status_code, 403)
        self.assertFalse(self.ws.messages)

    def test_rate_limit_and_request_size(self):
        for _ in range(5): self.assertEqual(self.login(key="wrong").status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        self.manager.attempts.clear()
        r = self.client.post("/management/api/session", headers=self.headers, content="x" * 2049)
        self.assertEqual(r.status_code, 413)

    def test_policy_revocation_invalidates_session(self):
        self.signin()
        self.cfg["users"]["joel"]["panels"] = []
        self.save_policy()
        self.assertEqual(self.run_check().status_code, 401)

    def test_session_idle_absolute_and_logout(self):
        for kind in ("idle", "absolute", "logout"):
            self.signin()
            s = next(iter(self.manager.sessions.values()))
            if kind == "idle": s["used"] -= 121
            elif kind == "absolute": s["expires"] = time.monotonic() - 1
            else:
                r = self.client.post("/management/api/logout", headers=self.headers)
                self.assertEqual(r.status_code, 200)
            self.assertEqual(self.run_check().status_code, 401)

    def test_no_shell_arguments_or_arbitrary_paths(self):
        self.signin()
        for op in ("sh", "uname -a", "../../etc/shadow", "health; reboot", "terminal"):
            self.assertEqual(self.run_check(op).status_code, 400)
        self.assertEqual(self.run_check(command="id").status_code, 400)
        self.assertFalse(self.ws.messages)

    def test_agent_enrollment_tls_optout_and_offline(self):
        self.signin()
        cases = [("plaintext", 409), ("legacy", 409), ("unsigned", 409), ("offline", 409), ("optout", 403)]
        for case, status in cases:
            self.manager.db = DB()
            self.live["study"] = WS(self.manager)
            next(iter(self.manager.sessions.values()))["last_run"] = -100
            if case == "plaintext": self.live["study"] = WS(self.manager, "ws")
            if case == "legacy": self.manager.db.token = ""
            if case == "unsigned": self.manager.db.sign = ""
            if case == "offline": self.live.clear()
            if case == "optout": self.manager.db.enabled = False
            self.assertEqual(self.run_check().status_code, status, case)

    def test_connection_reports_plaintext_without_remote_request(self):
        self.signin()
        self.ws.url = URL("ws://panels.example/api/ws/study")
        r = self.run_check("connection")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["agent_tls"])
        self.assertFalse(r.json()["shell_available"])
        self.assertFalse(self.ws.messages)

    def test_health_fixed_signed_request_and_filtered_response(self):
        self.signin()
        r = self.run_check()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["metrics"], {"cpu_temp": 64, "browser_health": "Healthy"})
        sent = self.ws.messages[0]
        self.assertEqual(set(sent), {"type", "request_id", "capture", "_sig"})
        self.assertFalse(sent["capture"])
        self.assertEqual(sent["type"], "screen_diagnostics")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertFalse(self.manager.pending)
        self.assertEqual(self.run_check().status_code, 429)

    def test_stale_wrong_panel_socket_responses_and_timeout(self):
        self.signin()
        with patch.object(m, "RESPONSE_S", 0.03):
            for behavior in ("silence", "wrong_id", "wrong_socket", "wrong_panel"):
                self.ws.behavior = behavior
                next(iter(self.manager.sessions.values()))["last_run"] = -100
                self.assertEqual(self.run_check().status_code, 504, behavior)
                self.assertFalse(self.manager.pending)

    def test_oversized_response(self):
        self.signin()
        self.ws.behavior = "large"
        self.assertEqual(self.run_check().status_code, 502)

    def test_inflight_revocation_rotation_and_socket_replacement(self):
        for behavior, status in (("revoke", 401), ("rotate", 409), ("replace", 409)):
            self.manager.sessions.clear()
            self.manager.db = DB()
            self.signin()
            self.ws = WS(self.manager)
            self.live["study"] = self.ws
            self.ws.behavior = behavior
            self.assertEqual(self.run_check().status_code, status, behavior)

    def test_audit_failure_denies_access_and_no_secrets_logged(self):
        response = self.signin()
        self.run_check()
        with closing(sqlite3.connect(self.audit)) as c:
            rows = c.execute("SELECT * FROM events").fetchall()
        self.assertTrue(any(row[1] == "diagnostic_end" for row in rows))
        for secret in (KEY, TOKEN, SIGN, response.json()["session"], "ha_token", "cpu_temp"):
            self.assertNotIn(secret, str(rows))
        with patch.dict(os.environ, PANEL_MANAGEMENT_AUDIT=str(self.root / "missing" / "audit.db")):
            self.assertEqual(self.login().status_code, 503)

    def test_page_assets_and_csp(self):
        r = self.client.get("/management/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("frame-ancestors 'self'", r.headers["content-security-policy"])
        self.assertIn('src="console.js"', r.text)
        self.assertEqual(self.client.get("/management/console.js").status_code, 200)
        self.assertEqual(self.client.get("/management/policy.json").status_code, 404)


if __name__ == "__main__": unittest.main(verbosity=2)
