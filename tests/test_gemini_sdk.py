"""Real Google SDK serialization/error handling over httpx.MockTransport; no live calls."""
import importlib.util
import json
import ssl
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch
from app.core.providers.llm_client import BackendError, LLMBackend, gemini_json_schema
from app.schemas.parser_schema import ParseResult, json_schema

try:
    SDK_AVAILABLE = importlib.util.find_spec("google.genai") is not None
except ModuleNotFoundError:
    SDK_AVAILABLE = False


@unittest.skipUnless(SDK_AVAILABLE, "Install requirements.txt for Google SDK integration tests")
class GeminiSDK(unittest.TestCase):
    def setUp(self):
        ssl.create_default_context()
        import httpx
        from google import genai
        self.httpx = httpx
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict("os.environ", {
            "GEMINI_API_KEY": "gemini-test-key-not-a-secret", "GEMINI_MODEL": "gemini-3.5-flash",
            "GEMINI_THINKING_LEVEL": "minimal", "GEMINI_TEMPERATURE": "",
            "GOOGLE_API_KEY": "must-not-use", "LLM_API_KEY": "must-not-use", "LLM_MODEL": "must-not-use",
            "GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_GEMINI_BASE_URL": "https://must-not-use.invalid",
        }, clear=True))
        self.calls, self.clients, self.options, self.sdk_closes = [], [], [], []
        self.responses = [(200, self.body())]
        actual_client = genai.Client

        def construct(**kwargs):
            self.options.append(kwargs)
            http_client = httpx.Client(transport=httpx.MockTransport(self.respond))
            self.stack.callback(http_client.close)
            self.clients.append(http_client)
            kwargs["http_options"].httpx_client = http_client
            client = actual_client(**kwargs)
            self.sdk_closes.append(self.stack.enter_context(patch.object(client, "close", wraps=client.close)))
            return client

        self.stack.enter_context(patch("google.genai.Client", side_effect=construct))

    def body(self, text=None, finish="STOP"):
        if text is None:
            text = json.dumps(ParseResult(order_id="ORD-045", parse_status="ok").to_dict())
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}]}

    def respond(self, request):
        self.calls.append(request)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        status, body = response
        return self.httpx.Response(status, json=body)

    def complete(self):
        backend = LLMBackend()
        try:
            return backend.complete("Allocate ORD-045.", date(2026, 4, 1)), None
        except BackendError as error:
            return None, str(error)
        finally:
            backend.close()

    def test_official_endpoint_key_model_and_schema(self):
        text, error = self.complete()
        self.assertIsNone(error)
        self.assertIn("ORD-045", text)
        request = self.calls[0]
        self.assertEqual(str(request.url),
                         "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent")
        self.assertEqual(request.headers["x-goog-api-key"], "gemini-test-key-not-a-secret")
        data = json.loads(request.content)
        config = data["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseJsonSchema"], gemini_json_schema())
        thinking = config["thinkingConfig"]
        self.assertEqual(thinking.get("thinkingLevel", thinking.get("thinking_level")).lower(), "minimal")
        fixtures = json.loads((Path(__file__).parent / "fixtures/prompt_messages_v1.json").read_text(encoding="utf-8"))
        original = next(case["expected"] for case in fixtures if case["profile"] == "llm" and case["feedback"] is None)
        self.assertEqual(data["systemInstruction"]["parts"][0]["text"],
                         "\n\n".join(m["content"] for m in original if m["role"] == "system"))
        self.assertEqual(self.options[0]["http_options"].retry_options.attempts, 1)
        self.assertIs(self.options[0]["vertexai"], False)
        self.assertTrue(all(close.call_count == 1 for close in self.sdk_closes))

    def test_generic_messages_use_the_supplied_output_contract(self):
        contract = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}
        self.responses = [(200, self.body(text='{"intent":"history"}'))]
        backend = LLMBackend()
        try:
            result = backend.generate([{"role": "system", "content": "Classify the request."},
                                       {"role": "user", "content": "Show history."}], output_schema=contract)
            self.assertEqual(result, '{"intent":"history"}')
            data = json.loads(self.calls[0].content)
            self.assertEqual(data["generationConfig"]["responseJsonSchema"], contract)
        finally:
            backend.close()

    def test_auth_error_no_body_leak(self):
        self.responses = [(403, {"error": {"code": 403, "message": "private service detail"}})]
        _, error = self.complete()
        self.assertEqual(error, "gemini_http_403")
        self.assertEqual(len(self.calls), 1)

    def test_blocked_prompt_stops(self):
        self.responses = [(200, {"promptFeedback": {"blockReason": "SAFETY"}})]
        _, error = self.complete()
        self.assertEqual(error, "gemini_refusal")

    def test_model_not_found_no_fallback(self):
        self.responses = [(404, {"error": {"code": 404, "message": "private model access detail"}})]
        _, error = self.complete()
        self.assertEqual(error, "gemini_http_404")
        self.assertEqual(len(self.calls), 1)

    def test_truncated_output_rejected(self):
        self.responses = [(200, self.body(finish="MAX_TOKENS"))]
        _, error = self.complete()
        self.assertEqual(error, "gemini_incomplete_output")

    def test_timeout_error(self):
        self.responses = [self.httpx.ReadTimeout("do not log this service detail")]
        _, error = self.complete()
        self.assertEqual(error, "gemini_connection_error")

    def test_empty_response_is_rejected(self):
        self.responses = [(200, {})]
        _, error = self.complete()
        self.assertEqual(error, "gemini_empty_response")

    def test_wire_nullable_enums_preserve_parser_contract(self):
        schema = gemini_json_schema()
        for field in ("objective", "category"):
            self.assertEqual(schema["properties"][field]["anyOf"][1], {"type": "null"})
            self.assertEqual(schema["properties"][field]["anyOf"][0]["enum"],
                             [v for v in json_schema()["properties"][field]["enum"] if v is not None])
        self.assertEqual(schema["required"], json_schema()["required"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
