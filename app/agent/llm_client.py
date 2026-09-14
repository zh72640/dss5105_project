"""Google's official Gemini SDK transport; no OpenAI compatibility endpoint."""
import math
import os
from copy import deepcopy
from app.schemas.parser_schema import json_schema
from .prompts import messages

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_PROVIDER = "google_gemini"


class BackendError(RuntimeError):
    def __init__(self, code, retryable=True):
        super().__init__(code)
        self.retryable = retryable


def gemini_json_schema():
    """Same v1 semantics, but nullable enums use JSON Schema anyOf for Gemini."""
    schema = deepcopy(json_schema())
    for prop in schema["properties"].values():
        if "enum" in prop and None in prop["enum"]:
            prop["anyOf"] = [{"type": "string", "enum": [v for v in prop.pop("enum") if v is not None]},
                             {"type": "null"}]
            prop.pop("type")
    return schema


class LLMBackend:
    name = "llm"
    provider = GEMINI_PROVIDER
    model = GEMINI_MODEL
    temperature = 0.0

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise BackendError("gemini_api_key_missing", retryable=False)
        try:
            timeout = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
            if not math.isfinite(timeout) or not 0 < timeout <= 300:
                raise ValueError()
        except ValueError as error:
            raise BackendError("gemini_invalid_timeout", retryable=False) from error
        # Lazy import keeps offline usage dependency-free.
        try:
            from google import genai
            from google.genai import errors, types
            from httpx import TransportError
        except ImportError as error:
            raise BackendError("gemini_sdk_missing", retryable=False) from error
        self.types = types
        self._api_error = errors.APIError
        self._transport_error = TransportError
        try:
            self.client = genai.Client(
                api_key=api_key, vertexai=False,
                http_options=types.HttpOptions(
                    base_url=GEMINI_BASE_URL, api_version="v1beta", timeout=round(timeout * 1000),
                    # The parser owns the single retry; prevent SDK's default extra retries.
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        except (ValueError, OSError) as error:
            raise BackendError("gemini_client_configuration_error", retryable=False) from error

    def complete(self, message, reference_date, feedback=None):
        types = self.types
        prompt = messages(message, reference_date, feedback)
        system = "\n\n".join(m["content"] for m in prompt if m["role"] == "system")
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part.from_text(text=m["content"])])
                    for m in prompt if m["role"] != "system"]
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system, temperature=self.temperature,
                    response_mime_type="application/json", response_json_schema=gemini_json_schema(),
                    candidate_count=1, max_output_tokens=4096,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                raise BackendError("gemini_refusal", retryable=False)
            if not response.candidates:
                raise BackendError("gemini_empty_response")
            candidate = response.candidates[0]
            if candidate.finish_reason != types.FinishReason.STOP:
                reason = candidate.finish_reason
                if reason == types.FinishReason.MAX_TOKENS:
                    raise BackendError("gemini_incomplete_output")
                raise BackendError("gemini_refusal", retryable=False)
            content = response.text
            if not isinstance(content, str) or not content.strip():
                raise BackendError("gemini_empty_response")
            return content
        except self._api_error as error:
            # Never log SDK error messages/bodies or credentials; stable code only.
            code = error.code
            retryable = code in (408, 429) or isinstance(code, int) and code >= 500
            raise BackendError(f"gemini_http_{code}", retryable=retryable) from error
        except (self._transport_error, TimeoutError, OSError) as error:
            raise BackendError("gemini_connection_error") from error
        except (ValueError, TypeError, KeyError) as error:
            raise BackendError("gemini_invalid_response", retryable=False) from error

    def close(self):
        self.client.close()
