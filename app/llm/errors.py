"""Application error policy for native LangChain model responses."""


class ModelSelectionError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class BackendError(RuntimeError):
    def __init__(self, code, retryable=True):
        super().__init__(code)
        self.retryable = retryable


def text_content(message):
    """Read native text and the output_text block accepted by the previous integration."""
    text = getattr(message, "text", "")
    if text:
        return text
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content
                       if isinstance(item, dict) and item.get("type") == "output_text")
    return ""


def check_response(message, *, require_text=True):
    """Reject incomplete or refused responses without altering the AIMessage."""
    content = getattr(message, "content", None)
    meta = getattr(message, "response_metadata", {}) or {}
    extra = getattr(message, "additional_kwargs", {}) or {}
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
    if require_text and not text_content(message).strip():
        raise BackendError("model_empty_response")
    return message


def check_structured(response):
    raw = response.get("raw") if isinstance(response, dict) else None
    if raw is None:
        raise BackendError("model_invalid_structured_output")
    check_response(raw, require_text=False)
    if response.get("parsing_error") or response.get("parsed") is None:
        raise BackendError("model_invalid_structured_output")
    return response["parsed"], raw


def translate_error(error, provider):
    if isinstance(error, (BackendError, ModelSelectionError)):
        return error
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return BackendError(f"{provider}_http_{status}", retryable=status in (408, 429) or status >= 500)
    name = type(error).__name__.lower()
    if isinstance(error, (TimeoutError, OSError)) or any(x in name for x in ("timeout", "connection", "transport")):
        return BackendError(provider + "_connection_error")
    return BackendError(provider + "_invalid_response", retryable=False)
