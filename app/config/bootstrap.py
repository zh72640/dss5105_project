"""Combine one environment snapshot with explicit application overrides."""
import os
from datetime import date

from app.config.model_settings import load_model_settings
from app.config.settings import Settings


def load_configuration(settings=None, model_settings=None, *, overrides=None):
    """Return configuration values; resource initialization belongs to lifespan."""
    overrides = dict(overrides or {})
    snapshot = dict(os.environ) if settings is None or model_settings is None else {}
    if overrides.get("model_key") is not None:
        snapshot["LLM_DEFAULT_MODEL"] = overrides["model_key"]
    if model_settings is None:
        model_settings = load_model_settings(
            snapshot, mode=overrides.get("mode"),
            legacy_backend=overrides.get("backend") or (settings.backend if settings else None))
    if settings is None:
        business_date = snapshot.get("DISPATCH_AS_OF", "")
        settings = Settings(
            db_path=overrides.get("db_path") or snapshot.get("DISPATCH_DB") or Settings.db_path,
            backend=model_settings.default_mode,
            as_of=overrides.get("as_of") or (date.fromisoformat(business_date) if business_date else None),
            require_auth=(overrides["require_auth"] if overrides.get("require_auth") is not None
                          else snapshot.get("DISPATCH_NO_AUTH", "0") != "1"))
    return settings, model_settings
