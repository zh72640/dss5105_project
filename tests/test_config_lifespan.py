"""Startup configuration, resource ownership, and compatibility contracts."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.config.bootstrap import load_configuration
from app.config.model_settings import load_model_settings
from app.config.settings import Settings
from app.main import create_app


class ConfigurationLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "startup.sqlite3")

    def test_factory_defers_configuration_and_database_until_lifespan(self):
        with patch("app.core.lifespan.load_configuration", side_effect=AssertionError("loaded too early")):
            app = create_app(Settings(db_path=self.path))
            self.assertIn("/api/chat/sessions", app.openapi()["paths"])
            self.assertNotIn("/api/requests", app.openapi()["paths"])
            self.assertNotIn("/api/sessions", app.openapi()["paths"])
        self.assertFalse(Path(self.path).exists())
        self.assertFalse(hasattr(app.state, "model_registry"))

    def test_environment_is_loaded_at_startup_once_and_request_limit_uses_settings(self):
        env = {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "startup-model"}
        model = Mock()
        factory = Mock(return_value=model)
        with patch.dict(os.environ, env, clear=True), \
             patch("app.config.bootstrap.load_model_settings", wraps=load_model_settings) as loader:
            app = create_app(Settings(db_path=self.path, require_auth=False, max_body_bytes=64),
                             model_factory=factory)
            with TestClient(app) as client:
                loader.assert_called_once()
                self.assertEqual(factory.call_args.args[0].api_model_id, "startup-model")
                with patch.dict(os.environ, {"OPENAI_MODEL": "changed"}):
                    self.assertEqual(client.get("/api/models").json()["models"][0]["model"], "startup-model")
                    self.assertEqual(client.post("/api/chat/sessions", json={"message": "x" * 100}).status_code, 413)
                loader.assert_called_once()
                factory.assert_called_once()
        model.close.assert_called_once()

    def test_environment_defaults_and_cli_overrides_share_one_loader(self):
        with patch.dict(os.environ, {"DISPATCH_DB": self.path, "DISPATCH_AS_OF": "2026-04-02",
                                    "DISPATCH_NO_AUTH": "1", "AGENT_MODE": "offline"}, clear=True):
            settings, models = load_configuration()
            self.assertEqual((settings.db_path, settings.as_of, settings.require_auth),
                             (self.path, date(2026, 4, 2), False))
            self.assertEqual(models.default_mode, "offline")
            settings, models = load_configuration(overrides={"db_path": "override.sqlite3",
                "as_of": date(2026, 4, 3), "require_auth": True, "mode": "llm"})
            self.assertEqual((settings.db_path, settings.as_of, settings.require_auth),
                             ("override.sqlite3", date(2026, 4, 3), True))
            self.assertEqual(models.default_mode, "llm")

    def test_registry_failure_closes_models(self):
        registry = Mock()
        app = create_app(Settings(db_path=self.path))
        with patch("app.core.lifespan.ModelRegistry", return_value=registry), \
             patch("app.core.lifespan.initialize_checkpoints", side_effect=RuntimeError("startup failed")), \
             self.assertRaisesRegex(RuntimeError, "startup failed"):
            with TestClient(app):
                pass
        registry.close.assert_called_once()

    def test_canonical_settings_modules_are_importable(self):
        from app.config import settings as settings_mod
        from app.config import model_settings as model_settings_mod
        self.assertIs(Settings, settings_mod.Settings)
        self.assertIs(load_model_settings, model_settings_mod.load_model_settings)


if __name__ == "__main__":
    unittest.main()
