"""Normalize different provider content blocks without logging response bodies."""
import json
from app.core.model_errors import BackendError


def normalize_response(response):
    structured = isinstance(response, dict) and "raw" in response
    raw = response["raw"] if structured else response
    content = getattr(raw, "content", None)
    meta = getattr(raw, "response_metadata", {}) or {}
    extra = getattr(raw, "additional_kwargs", {}) or {}
    finish = str(meta.get("finish_reason", meta.get("stop_reason", ""))).upper().split(".")[-1]
    refusal_block = isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "refusal" for item in content)
    blocked = (meta.get("prompt_feedback") or {}).get("block_reason")
    if extra.get("refusal") or refusal_block or blocked or finish in ("CONTENT_FILTER", "SAFETY", "REFUSAL"):
        raise BackendError("model_refusal", retryable=False)
    if finish in ("LENGTH", "MAX_TOKENS", "MAX_OUTPUT_TOKENS") or meta.get("status") == "incomplete":
        raise BackendError("model_incomplete_output")
    if meta.get("status") == "failed":
        raise BackendError("model_failed_response", retryable=False)
    if structured:
        if response.get("parsing_error") or response.get("parsed") is None:
            raise BackendError("model_invalid_structured_output")
        parsed = response["parsed"]
        text = json.dumps(parsed.model_dump() if hasattr(parsed, "model_dump") else parsed, allow_nan=False)
    else:
        text = content if isinstance(content, str) else "".join(
            item.get("text", "") for item in content or []
            if isinstance(item, dict) and item.get("type") in ("text", "output_text"))
    if not isinstance(text, str) or not text.strip():
        raise BackendError("model_empty_response")
    return {"text": text, "usage": getattr(raw, "usage_metadata", None), "finish_reason": finish}


def translate_error(error, provider):
    if isinstance(error, BackendError):
        return error
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return BackendError(f"{provider}_http_{status}", retryable=status in (408, 429) or status >= 500)
    name = type(error).__name__.lower()
    if isinstance(error, (TimeoutError, OSError)) or any(x in name for x in ("timeout", "connection", "transport")):
        return BackendError(provider + "_connection_error")
    return BackendError(provider + "_invalid_response", retryable=False)
