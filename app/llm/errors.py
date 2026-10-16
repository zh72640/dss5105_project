"""Application error policy for native LangChain model responses."""


class ModelSelectionError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class BackendError(RuntimeError):
    def __init__(self, code, retryable=True, *, provider=None, upstream_status=None,
                 original_type=None, cause_types=()):
        super().__init__(code)
        self.retryable = retryable
        self.provider = provider
        self.upstream_status = upstream_status
        self.original_type = original_type
        self.cause_types = list(cause_types)

    def details(self):
        """Safe diagnostics: never expose provider response bodies or credentials."""
        return {"code": str(self), "retryable": self.retryable, "provider": self.provider,
                "upstream_status": self.upstream_status, "original_type": self.original_type,
                "cause_types": self.cause_types}

    def user_message(self):
        provider = {"gemini": "Gemini", "openai": "OpenAI", "claude": "Claude",
                    "deepseek": "DeepSeek"}.get(self.provider, "The model service")
        status = self.upstream_status
        suffix = f" (HTTP {status})" if status else ""
        if status in (401, 403):
            return f"{provider} rejected authentication or access{suffix}. Check the model credentials and permissions."
        if status == 429:
            return f"{provider} reached a rate or quota limit{suffix}. Wait before retrying this request."
        if status and (status >= 500 or status == 408):
            return f"{provider} is temporarily unavailable{suffix}. Retry this request to resume."
        if status:
            return f"{provider} rejected the model request{suffix}. Check the model configuration before starting a new request."
        if str(self).endswith("_connection_error"):
            return f"The connection to {provider} timed out or failed. Retry this request to resume."
        if str(self).endswith('_invalid_input'):
            return "The model request is missing required message content."
        if self.retryable:
            return "The model returned an incomplete or unusable response. Retry this request to resume."
        return "The model request could not be completed. Check the model configuration or input."


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
    chain, seen = [], set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    details = {"provider": provider, "original_type": type(error).__name__,
               "cause_types": [type(item).__name__ for item in chain[1:]]}
    for item in chain:
        # Gemini exposes `code`; OpenAI and Anthropic expose `status_code`.
        for status in (getattr(item, "status_code", None), getattr(item, "code", None),
                       getattr(getattr(item, "response", None), "status_code", None)):
            if isinstance(status, int) and not isinstance(status, bool) and 400 <= status <= 599:
                return BackendError(f"{provider}_http_{status}",
                    retryable=status in (408, 429) or status >= 500, upstream_status=status, **details)
    missing_content_errors = {'contents are required.', 'content is required.', 'content parts are required.'}
    if any(isinstance(item, ValueError) and str(item).strip() in missing_content_errors for item in chain):
        return BackendError(provider + '_invalid_input', retryable=False, **details)
    if any(isinstance(item, (TimeoutError, OSError)) or any(
            name in type(item).__name__.lower() for name in ("timeout", "connection", "transport"))
            for item in chain):
        return BackendError(provider + "_connection_error", **details)
    return BackendError(provider + "_invalid_response", retryable=False, **details)
