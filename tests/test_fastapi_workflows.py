"""Contracts and durable workflow boundaries introduced by the framework migration."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.services.lifecycle import inspect_order
from app.services.dispatch import seed_allocation


class FastAPIContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "desk.sqlite3")
        self.client = self.enterContext(TestClient(create_app(Settings(db_path=self.path, require_auth=False))))

    def test_openapi_documents_chat_cookie_and_events(self):
        schema = self.client.get("/openapi.json").json()
        for path in ("/api/chat/sessions", "/api/chat/sessions/{session_id}/turns", "/api/events"):
            self.assertIn(path, schema["paths"])
        for path in ("/api/sessions", "/api/requests", "/api/jobs"):
            self.assertNotIn(path, schema["paths"])
        self.assertEqual(schema["components"]["securitySchemes"]["APIKeyCookie"]["in"], "cookie")
        self.assertIn("ChatTurnInput", schema["components"]["schemas"])
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/redoc").status_code, 200)

    def test_validation_does_not_echo_passwords(self):
        response = self.client.post("/api/auth/login", json={"username": "x", "password": ["secret-value"]})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("secret-value", response.text)
        self.assertEqual(self.client.post("/api/chat/sessions", content="{",
            headers={"Content-Type": "application/json"}).json()["error"], "INVALID_JSON")

    def test_size_origin_headers_and_static_asset_paths(self):
        response = self.client.post("/api/chat/sessions", json={"request_id": "r"},
                                    headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/chat/sessions", content="x" * 50001,
            headers={"Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.get("/").content, self.client.get("/?filename=../core/config.py").content)
        self.assertIn("x-request-id", self.client.get("/api/health").headers)

    def test_production_factory_requires_explicit_database_initialization(self):
        missing = str(Path(self.temp.name) / "uninitialized.sqlite3")
        with patch.dict("os.environ", {"DISPATCH_DB": missing}):
            with self.assertRaises(ValueError):
                with TestClient(create_app()):
                    pass
        self.assertFalse(Path(missing).exists())

    def test_checkpoints_and_wal_are_initialized_at_startup(self):
        path = str(Path(self.temp.name) / "startup.sqlite3")
        app = create_app(Settings(db_path=path, require_auth=False))
        with TestClient(app):
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertIsNotNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='checkpoints'").fetchone())


class LifecycleSeed(unittest.TestCase):
    def test_offline_seed_allocation_still_works_for_production_tests(self):
        path = str(Path(tempfile.mkdtemp()) / "seed.sqlite3")
        payload = seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=path)
        self.assertEqual(payload["result"]["decision_status"], "ALLOCATE")
        order = inspect_order("ORD-045", db_path=path)
        self.assertEqual(order["state"], "WORKING")


if __name__ == "__main__":
    unittest.main()
