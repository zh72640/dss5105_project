"""Authentication, desk read models, exports and production approval integrity."""
import json
import tempfile
import threading
import time
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app.core import security as auth
from app.db.database import Database
from app.services.allocation.dispatch import seed_allocation
from app.services.production.lifecycle import process_event
from app.server import make_server

PASSWORD = "A-test-only-password-2026"


class DeskHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "desk.sqlite3"
        auth.set_password(self.path, "operator", PASSWORD)
        self.server = make_server(0, self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.cookies = CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.cookies))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def call(self, path, body=None, **headers):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json", **headers})
        try:
            response = self.client.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            value = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
            return response.status, value, response.headers

    def login(self):
        status, _, headers = self.call("/api/auth/login", {"username": "operator", "password": PASSWORD})
        self.assertEqual(status, 200)
        return headers

    def test_login_gates_reads_and_logout_revokes_cookie(self):
        self.assertIsNone(self.call("/api/auth/me")[1]["username"])
        for path in ("/api/ai/status", "/api/dashboard", "/api/workshops", "/api/audit",
                     "/api/audit/export", "/api/orders/ORD-045", "/api/history", "/api/chat/sessions"):
            self.assertEqual(self.call(path)[0], 401, path)
        self.assertEqual(self.call("/api/auth/login", {"username": "operator", "password": "wrong"})[0], 401)
        headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertEqual(self.call("/api/dashboard")[0], 200)
        token = next(iter(self.cookies)).value
        self.assertEqual(self.call("/api/auth/logout", {})[0], 200)
        self.assertIsNone(auth.identify(self.path, token))
        self.assertEqual(self.call("/api/audit")[0], 401)

    def test_login_origin_rate_limit(self):
        self.assertEqual(self.call("/api/auth/login", {"username": "operator", "password": PASSWORD},
                                   Origin="https://evil.example")[0], 403)
        self.login()
        self.assertEqual(self.call("/api/chat/sessions", {"request_id": "x"},
                                   Origin="https://evil.example")[0], 403)
        for _ in range(9):
            self.call("/api/auth/login", {"username": "operator", "password": "wrong"})
        self.assertEqual(self.call("/api/auth/login", {"username": "operator", "password": "wrong"})[0], 429)

    def test_dashboard_workshops_and_audit_export(self):
        self.login()
        seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=str(self.path), request_id="desk-alloc")
        dash = self.call("/api/dashboard")[1]
        self.assertIn("stats", dash)
        self.assertTrue(self.call("/api/workshops")[1]["items"])
        status, body, _ = self.call("/api/audit/export")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body.get("total", len(body.get("items", []))), 1)

    def test_production_event_via_http_after_seed(self):
        self.login()
        seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=str(self.path), request_id="prod")
        order = self.call("/api/orders/ORD-045")[1]
        status, result, _ = self.call("/api/events", {
            "action": "cancel", "order_id": "ORD-045", "actor": "operator",
            "reason": "Change plan", "expected_version": order["version"], "event_id": "cancel-1"})
        self.assertEqual(status, 200)
        self.assertEqual(result["order"]["state"], "READY")


class DeskIntegrity(unittest.TestCase):
    def test_seed_allocation_and_event_are_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "integrity.sqlite3"
            seed_allocation("Allocate ORD-045.", db_path=str(path), request_id="a1")
            with Database(str(path)) as db:
                order = db.connection.execute(
                    "SELECT state FROM orders WHERE order_id='ORD-045'").fetchone()
                self.assertEqual(order["state"], "WORKING")
            process_event("cancel", "ORD-045", actor="tester", reason="undo",
                          expected_version=1, event_id="e1", db_path=str(path))


class DeskAuthCookies(unittest.TestCase):
    def test_lapsed_session_cookie_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "auth.sqlite3"
            auth.set_password(path, "operator", PASSWORD)
            server = make_server(0, path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            cookies = CookieJar()
            client = build_opener(HTTPCookieProcessor(cookies))
            try:
                client.open(Request(base + "/api/auth/login",
                    data=json.dumps({"username": "operator", "password": PASSWORD}).encode(),
                    headers={"Content-Type": "application/json"}), timeout=5).read()
                with patch("app.core.security.time.time", return_value=time.time() + auth.TTL + 1):
                    try:
                        client.open(base + "/api/dashboard", timeout=5)
                        self.fail("expected 401")
                    except HTTPError as error:
                        self.assertEqual(error.code, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
