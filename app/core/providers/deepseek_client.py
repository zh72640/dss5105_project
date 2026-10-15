"""DeepSeek JSON transport. Credentials stay in the server process environment."""
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .llm_client import BackendError
from app.prompts.parser_v1 import messages, parser_snapshot
from app.prompts import PromptCatalogError, PromptRenderError, RenderedPrompt

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-flash"


def default_backend():
    return os.getenv("PARSER_BACKEND") or ("deepseek" if os.getenv("DEEPSEEK_API_KEY", "").strip() else "offline")


def model_name():
    model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip()
    if not re.fullmatch(r"deepseek-[a-zA-Z0-9.-]{1,80}", model):
        raise BackendError("deepseek_invalid_model", retryable=False)
    return model


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to a redirected destination.
        return None


class DeepSeekBackend:
    name = "deepseek"
    provider = "deepseek"
    temperature = 0

    def __init__(self):
        self._key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not self._key:
            raise BackendError("deepseek_api_key_missing", retryable=False)
        if any(ord(c) < 33 or ord(c) > 126 for c in self._key):
            raise BackendError("deepseek_invalid_api_key", retryable=False)
        self.model = model_name()
        try:
            self.timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))
            if not math.isfinite(self.timeout) or not 0 < self.timeout <= 300:
                raise ValueError()
        except ValueError:
            raise BackendError("deepseek_invalid_timeout", retryable=False) from None
        self._prompt_snapshot = parser_snapshot("deepseek")
        self._opener = build_opener(NoRedirect())

    @property
    def prompt_metadata(self):
        return self._prompt_snapshot.metadata

    def complete(self, message, reference_date, feedback=None):
        try:
            prompt = messages(message, reference_date, feedback, snapshot=self._prompt_snapshot)
        except (PromptCatalogError, PromptRenderError) as error:
            raise BackendError("prompt_configuration_error", retryable=False) from error
        return self.generate(prompt, json_output=True)

    def generate(self, prompt, *, output_schema=None, json_output=False):
        """Send any prepared prompt; callers include schema hints and validate outputs."""
        if isinstance(prompt, RenderedPrompt):
            prompt = prompt.as_messages()
        body = {"model": self.model, "messages": prompt, "stream": False,
                "max_tokens": 4096, "temperature": self.temperature, "thinking": {"type": "disabled"}}
        if json_output or output_schema is not None:
            body["response_format"] = {"type": "json_object"}
        request = Request(DEEPSEEK_URL, data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + self._key})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise BackendError("deepseek_response_too_large", retryable=False)
            data = json.loads(raw)
            choice = data["choices"][0]
            reason = choice["finish_reason"]
            if reason == "length":
                raise BackendError("deepseek_incomplete_output")
            if reason != "stop":
                raise BackendError("deepseek_refusal", retryable=False)
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise BackendError("deepseek_empty_response")
            return content
        except HTTPError as error:
            code = error.code
            error.close()
            raise BackendError(f"deepseek_http_{code}", retryable=code in (408, 429) or code >= 500) from None
        except (URLError, TimeoutError, OSError):
            raise BackendError("deepseek_connection_error") from None
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
            raise BackendError("deepseek_invalid_response") from None

    def close(self):
        self._key = ""


def backend_status(backend):
    """Allowlisted metadata only. A configured key does not prove remote validity."""
    status = {"backend": backend, "configured": True, "model": "rules_v1"}
    if backend == "deepseek":
        status["configured"] = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
        try:
            status["model"] = model_name()
        except BackendError:
            status.update(model=None, configured=False)
    elif backend == "llm":
        from .llm_client import gemini_model
        try:
            status.update(model=gemini_model(), configured=bool(os.getenv("GEMINI_API_KEY", "").strip()))
        except BackendError:
            status.update(model=None, configured=False)
    return status
