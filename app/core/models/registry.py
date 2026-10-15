"""Application-owned model catalogue and request-local selection."""
import threading
from dataclasses import replace
from app.prompts.parser_v1 import parser_snapshot
from app.core.models.factory import build_model
from app.core.models.specs import ModelSelectionError, ResolvedSelection
from app.core.models.result import normalize_response, translate_error


class ModelRegistry:
    def __init__(self, settings, factory=build_model):
        self.settings, self.factory = settings, factory
        self.models = {spec.key: spec for spec in settings.models}
        self.prompt = parser_snapshot("deepseek")
        self._instances, self._errors = {}, {}
        self._task_instances = {}
        self._task_lock = threading.RLock()

    def initialize(self):
        for spec in self.models.values():
            if spec.configured:
                try:
                    self._instances[spec.key] = self.factory(spec)
                except Exception:
                    self._errors[spec.key] = "MODEL_INITIALIZATION_FAILED"

    def resolve(self, mode=None, model_key=None, *, require_model=True):
        mode = mode or self.settings.default_mode
        if mode not in ("llm", "offline"):
            raise ModelSelectionError("INVALID_ARGUMENT", "Mode must be llm or offline.")
        if mode == "offline":
            if model_key is not None:
                raise ModelSelectionError("INVALID_ARGUMENT", "Offline mode does not accept a model selection.")
            return ResolvedSelection(mode, None, self.prompt.metadata["content_hash"])
        key = model_key or self.settings.default_model
        if key is not None and key not in self.models:
            raise ModelSelectionError("UNKNOWN_MODEL", "Choose a model listed by /api/models.")
        spec = self.models.get(key)
        if require_model and (spec is None or not spec.configured):
            raise ModelSelectionError("MODEL_NOT_CONFIGURED", "No API key/model is configured. Configure a model or use Offline.", 503)
        if require_model and key in self._errors:
            raise ModelSelectionError("MODEL_INITIALIZATION_FAILED", "The model integration could not be initialized.", 503)
        return ResolvedSelection(mode, spec, self.prompt.metadata["content_hash"])

    def invoke(self, selection, prepared_messages):
        spec = selection.spec
        model = self._instances.get(spec.key) if spec else None
        if model is None:
            from app.core.model_errors import BackendError
            raise BackendError("model_not_configured", retryable=False)
        try:
            return normalize_response(model.invoke(prepared_messages))
        except Exception as error:
            raise translate_error(error, spec.provider) from None

    def invoke_task(self, mode, model_key, bundle):
        """Task prompts must not inherit the frozen parser structured-output schema."""
        selection = self.resolve(mode, model_key)
        selection = replace(selection, prompt_hash=bundle.metadata['content_hash'])
        spec = selection.spec
        with self._task_lock:
            if spec.key not in self._task_instances:
                self._task_instances[spec.key] = self.factory(replace(spec, output_method='prompt'))
            model = self._task_instances[spec.key]
        try:
            result = normalize_response(model.invoke(bundle.as_messages()))
        except Exception as error:
            raise translate_error(error, spec.provider) from None
        return result, {**selection.metadata, 'prompt': bundle.metadata}

    def require_native_tools(self, mode, model_key):
        """Check capability before entering a tool-driven graph."""
        selection = self.resolve(mode, model_key)
        spec = selection.spec
        with self._task_lock:
            if spec.key not in self._task_instances:
                self._task_instances[spec.key] = self.factory(replace(spec, output_method='prompt'))
            model = self._task_instances[spec.key]
        if not callable(getattr(model, 'bind_tools', None)):
            raise ModelSelectionError('TOOLS_UNSUPPORTED',
                'The selected model does not support native tool calls.', 503)

    def invoke_tools(self, mode, model_key, messages, tool_schemas):
        """Invoke a native provider tool call; never parse a JSON plan from text."""
        selection = self.resolve(mode, model_key)
        spec = selection.spec
        with self._task_lock:
            if spec.key not in self._task_instances:
                self._task_instances[spec.key] = self.factory(replace(spec, output_method='prompt'))
            model = self._task_instances[spec.key]
        if not callable(getattr(model, 'bind_tools', None)):
            raise ModelSelectionError('TOOLS_UNSUPPORTED', 'The selected model does not support native tool calls.', 503)
        try:
            response = model.bind_tools(tool_schemas).invoke(messages)
        except Exception as error:
            raise translate_error(error, spec.provider) from None
        if not hasattr(response, 'tool_calls'):
            raise ModelSelectionError('TOOLS_UNSUPPORTED', 'The selected model returned no tool-call structure.', 503)
        return response

    def public(self):
        return {"default_mode": self.settings.default_mode, "default_model": self.settings.default_model,
                "models": [{**spec.public(), "available": spec.configured and spec.key not in self._errors,
                            "error": self._errors.get(spec.key)} for spec in self.models.values()]}

    def close(self):
        seen = set()
        for model in (*self._instances.values(), *self._task_instances.values()):
            base = getattr(model, "first", model)
            # SDK integrations own these clients. Close each unique resource once.
            for name in ("root_client", "client"):
                client = getattr(base, name, None)
                if client is not None and id(client) not in seen and callable(getattr(client, "close", None)):
                    seen.add(id(client))
                    client.close()


_runtimes, _runtime_lock = {}, threading.RLock()


def register_runtime(db_path, registry):
    with _runtime_lock:
        _runtimes[str(db_path)] = registry




def unregister_runtime(db_path, registry):
    with _runtime_lock:
        if _runtimes.get(str(db_path)) is registry:
            _runtimes.pop(str(db_path), None)


def background_runtime():
    """The existing jobs worker owns a single application per process."""
    with _runtime_lock:
        return next(iter(_runtimes.values())) if len(_runtimes) == 1 else None
