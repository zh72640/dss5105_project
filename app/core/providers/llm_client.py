"""Google's official Gemini SDK transport; no OpenAI compatibility endpoint."""
import math
import os
from copy import deepcopy
from app.schemas.parser_schema import json_schema
from app.core.model_errors import BackendError
from app.prompts.parser_v1 import messages, parser_snapshot
from app.prompts import PromptCatalogError, PromptRenderError, RenderedPrompt

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_PROVIDER = "google_gemini"
_DEFAULT_MODEL = "gemini-3.5-flash"
_DEFAULT_THINKING_LEVEL = "minimal"


def gemini_model():
    model = os.getenv("GEMINI_MODEL", _DEFAULT_MODEL).strip()
    if not model:
        raise BackendError("gemini_invalid_model", retryable=False)
    return model


def gemini_temperature():
    raw = os.getenv("GEMINI_TEMPERATURE")
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise BackendError("gemini_invalid_temperature", retryable=False) from error
    if not math.isfinite(value):
        raise BackendError("gemini_invalid_temperature", retryable=False)
    return value


def gemini_thinking_level():
    level = os.getenv("GEMINI_THINKING_LEVEL", _DEFAULT_THINKING_LEVEL).strip()
    if not level:
        raise BackendError("gemini_invalid_thinking_level", retryable=False)
    return level




def adapt_json_schema(schema):
    """Adapt nullable string enums recursively without changing caller-owned schemas."""
    schema = deepcopy(schema)
    def adapt(node):
        if isinstance(node, dict):
            values = node.get("enum")
            if isinstance(values, list) and None in values and all(isinstance(v, str) for v in values if v is not None):
                node["anyOf"] = [{"type": "string", "enum": [v for v in node.pop("enum") if v is not None]},
                                 {"type": "null"}]
                node.pop("type", None)
            for child in node.values():
                adapt(child)
        elif isinstance(node, list):
            for child in node:
                adapt(child)
    adapt(schema)
    return schema


def gemini_json_schema():
    return adapt_json_schema(json_schema())


class LLMBackend:
    name = "llm"
    provider = GEMINI_PROVIDER

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
        self.model = gemini_model()
        self.temperature = gemini_temperature()
        self.thinking_level = gemini_thinking_level()
        self._prompt_snapshot = parser_snapshot("llm")
        # Lazy import keeps offline usage independent of the model SDK.
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

    @property
    def prompt_metadata(self):
        return self._prompt_snapshot.metadata

    def complete(self, message, reference_date, feedback=None):
        try:
            prompt = messages(message, reference_date, feedback, snapshot=self._prompt_snapshot)
        except (PromptCatalogError, PromptRenderError) as error:
            raise BackendError("prompt_configuration_error", retryable=False) from error
        return self.generate(prompt, output_schema=gemini_json_schema())

    def generate(self, prompt, *, output_schema=None, json_output=False):
        """Send any prepared prompt with a function-specific optional output schema."""
        types = self.types
        if isinstance(prompt, RenderedPrompt):
            prompt = prompt.as_messages()
        system = "\n\n".join(m["content"] for m in prompt if m["role"] == "system")
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part.from_text(text=m["content"])])
                    for m in prompt if m["role"] != "system"]
        config = {
            "system_instruction": system, "candidate_count": 1, "max_output_tokens": 4096,
            "thinking_config": types.ThinkingConfig(thinking_level=self.thinking_level),
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if json_output or output_schema is not None:
            config["response_mime_type"] = "application/json"
        if output_schema is not None:
            config["response_json_schema"] = adapt_json_schema(output_schema)
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=types.GenerateContentConfig(**config),
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
