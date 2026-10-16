"""Startup-only environment parsing. No model invocation reads the environment."""
import json
import math
import os
import re
from app.llm.specs import ModelSettings, ModelSpec

PROVIDERS = (
    ("openai", "OPENAI", "OPENAI_API_KEY", None),
    ("claude", "ANTHROPIC", "ANTHROPIC_API_KEY", None),
    ("gemini", "GEMINI", "GEMINI_API_KEY", "gemini-3.5-flash"),
    ("deepseek", "DEEPSEEK", "DEEPSEEK_API_KEY", "deepseek-flash"),
)
OPTION_KEYS = {"temperature", "max_tokens", "max_output_tokens", "reasoning_effort",
               "thinking", "thinking_level", "max_completion_tokens"}


def _json_object(raw, label):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate key in {label}.")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be a JSON object.") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def load_model_settings(env=None, *, mode=None, legacy_backend=None):
    """Call at application startup; pass the snapshot explicitly to all integrations."""
    snapshot = dict(os.environ) if env is None else dict(env)
    legacy = legacy_backend or snapshot.get("PARSER_BACKEND")
    selected_mode = mode or snapshot.get("AGENT_MODE") or ("offline" if legacy == "offline" else "llm")
    if selected_mode not in ("offline", "llm"):
        raise ValueError("AGENT_MODE must be offline or llm.")
    models, keys = [], set()
    for provider, prefix, key_name, old_default in PROVIDERS:
        credential = snapshot.get(key_name, "").strip()
        raw_models = snapshot.get(prefix + "_MODELS", "").strip()
        single = snapshot.get(prefix + "_MODEL", "").strip()
        if raw_models:
            entries = _json_object(raw_models, prefix + "_MODELS")
        elif single or (credential and old_default):
            entries = {provider: single or old_default}
        else:
            continue
        try:
            timeout = float(snapshot.get(prefix + "_TIMEOUT_SECONDS", "30"))
            if not math.isfinite(timeout) or not 0 < timeout <= 300:
                raise ValueError()
        except ValueError:
            raise ValueError(prefix + "_TIMEOUT_SECONDS must be in (0, 300].") from None
        options = _json_object(snapshot.get(prefix + "_OPTIONS", "{}"), prefix + "_OPTIONS")
        if set(options) - OPTION_KEYS:
            raise ValueError(prefix + "_OPTIONS contains unsupported parameters.")
        temperature = snapshot.get(prefix + "_TEMPERATURE", "").strip()
        if temperature:
            try:
                temperature = float(temperature)
                if not math.isfinite(temperature):
                    raise ValueError()
            except ValueError:
                raise ValueError(prefix + "_TEMPERATURE must be finite.") from None
            options.setdefault("temperature", temperature)
        if provider == "gemini" and snapshot.get("GEMINI_THINKING_LEVEL", "").strip():
            options.setdefault("thinking_level", snapshot["GEMINI_THINKING_LEVEL"].strip())
        output = snapshot.get(prefix + "_STRUCTURED_OUTPUT", "prompt").strip()
        if output not in ("prompt", "json_schema", "json_mode", "function_calling"):
            raise ValueError(prefix + "_STRUCTURED_OUTPUT has an unsupported method.")
        for alias, model in entries.items():
            if (not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", alias)
                    or not isinstance(model, str) or not model.strip() or len(model) > 200):
                raise ValueError(prefix + "_MODELS needs valid aliases and API model IDs.")
            if alias in keys:
                raise ValueError("Model aliases must be unique across providers.")
            keys.add(alias)
            models.append(ModelSpec(alias, provider, model.strip(), credential, timeout,
                                    output, json.dumps(options, sort_keys=True, allow_nan=False)))
    default = snapshot.get("LLM_DEFAULT_MODEL", "").strip() or None
    if default and default not in keys:
        raise ValueError("LLM_DEFAULT_MODEL is not a registered model alias.")
    if not default:
        preferred = "gemini" if legacy == "llm" else "deepseek" if legacy == "deepseek" else None
        eligible = [m for m in models if m.configured]
        first = next((m for m in eligible if m.provider == preferred), None)
        default = first.key if first else eligible[0].key if eligible else models[0].key if models else None
    return ModelSettings(selected_mode, default, tuple(models))
