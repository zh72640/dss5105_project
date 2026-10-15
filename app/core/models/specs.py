from dataclasses import dataclass, field
import hashlib
import json


class ModelSelectionError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class ModelSpec:
    key: str
    provider: str
    api_model_id: str
    credential: str = field(repr=False)
    timeout: float = 30
    output_method: str = "prompt"
    options_json: str = "{}"

    @property
    def options(self):
        return json.loads(self.options_json)

    @property
    def configured(self):
        return bool(self.credential)

    def public(self):
        return {"model_key": self.key, "provider": self.provider,
                "model": self.api_model_id, "configured": self.configured}


@dataclass(frozen=True)
class ModelSettings:
    default_mode: str = "llm"
    default_model: str | None = None
    models: tuple[ModelSpec, ...] = ()


@dataclass(frozen=True)
class ResolvedSelection:
    mode: str
    spec: ModelSpec | None
    prompt_hash: str

    @property
    def metadata(self):
        spec = self.spec
        values = {"mode": self.mode, "model_key": spec.key if spec else None,
                  "provider": spec.provider if spec else "offline" if self.mode == "offline" else None,
                  "model": spec.api_model_id if spec else "rules_v1" if self.mode == "offline" else None,
                  "parameters": spec.options if spec else {},
                  "timeout": spec.timeout if spec else None,
                  "output_method": spec.output_method if spec else None,
                  "prompt_hash": self.prompt_hash, "selection_version": "models_v1"}
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return {**values, "signature": hashlib.sha256(encoded.encode()).hexdigest()}
