"""Application-scoped model catalogue and base LangChain chat models."""
import hashlib
import json
import threading

from langchain.chat_models import init_chat_model

from app.llm.errors import ModelSelectionError


INTEGRATIONS = {"openai": "openai", "claude": "anthropic",
                "gemini": "google_genai", "deepseek": "deepseek"}


def build_model(spec):
    """Create an unbound model from the immutable startup configuration."""
    options = spec.options
    options.setdefault("max_output_tokens" if spec.provider == "gemini" else "max_tokens", 4096)
    return init_chat_model(model=spec.api_model_id,
                           model_provider=INTEGRATIONS[spec.provider],
                           api_key=spec.credential, timeout=spec.timeout,
                           max_retries=0, **options)


def selection_metadata(mode, spec, prompt_hash=None):
    """Preserve the existing non-secret model audit fields."""
    values = {"mode": mode, "model_key": spec.key if spec else None,
              "provider": spec.provider if spec else "offline" if mode == "offline" else None,
              "model": spec.api_model_id if spec else "rules_v1" if mode == "offline" else None,
              "parameters": spec.options if spec else {},
              "timeout": spec.timeout if spec else None,
              "output_method": spec.output_method if spec else None,
              "prompt_hash": prompt_hash, "selection_version": "models_v1"}
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**values, "signature": hashlib.sha256(encoded.encode()).hexdigest()}


class ModelRegistry:
    def __init__(self, settings, factory=build_model):
        self.settings, self.factory = settings, factory
        self.models = {spec.key: spec for spec in settings.models}
        self._models, self._errors = {}, {}
        self._lock = threading.RLock()

    def initialize(self):
        for spec in self.models.values():
            if spec.configured:
                try:
                    self.get_model("llm", spec.key)
                except Exception:
                    self._errors[spec.key] = "MODEL_INITIALIZATION_FAILED"

    def resolve(self, mode=None, model_key=None, *, require_model=True):
        mode = mode or self.settings.default_mode
        if mode not in ("llm", "offline"):
            raise ModelSelectionError("INVALID_ARGUMENT", "Mode must be llm or offline.")
        if mode == "offline":
            if model_key is not None:
                raise ModelSelectionError("INVALID_ARGUMENT", "Offline mode does not accept a model selection.")
            return None
        key = model_key or self.settings.default_model
        if key is not None and key not in self.models:
            raise ModelSelectionError("UNKNOWN_MODEL", "Choose a model listed by /api/models.")
        spec = self.models.get(key)
        if require_model and (spec is None or not spec.configured):
            raise ModelSelectionError("MODEL_NOT_CONFIGURED",
                "No API key/model is configured. Configure a model or use Offline.", 503)
        if require_model and key in self._errors:
            raise ModelSelectionError("MODEL_INITIALIZATION_FAILED",
                "The model integration could not be initialized.", 503)
        return spec

    def get_model(self, mode, model_key):
        spec = self.resolve(mode, model_key)
        with self._lock:
            if spec.key not in self._models:
                self._models[spec.key] = self.factory(spec)
            return self._models[spec.key]

    def public(self):
        return {"default_mode": self.settings.default_mode, "default_model": self.settings.default_model,
                "models": [{**spec.public(), "available": spec.configured and spec.key not in self._errors,
                            "error": self._errors.get(spec.key)} for spec in self.models.values()]}

    def close(self):
        for model in self._models.values():
            close = getattr(model, "close", None)
            if callable(close):
                close()
        self._models.clear()
