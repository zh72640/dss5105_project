import io
import json
import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from app.core.providers.deepseek_client import DeepSeekBackend, NoRedirect, backend_status, default_backend
from app.core.providers.llm_client import BackendError
from app.schemas.parser_schema import ParseResult


class DeepSeekTransport(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-not-a-real-key"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.opener = MagicMock()
        factory = patch("app.core.providers.deepseek_client.build_opener", return_value=self.opener)
        factory.start()
        self.addCleanup(factory.stop)

    def reply(self, content=None, reason="stop"):
        if content is None:
            content = json.dumps(ParseResult(order_id="ORD-045", parse_status="ok").to_dict())
        self.opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"finish_reason": reason, "message": {"content": content}}]}).encode()

    def complete(self):
        try:
            return DeepSeekBackend().complete("Allocate ORD-045.", date(2026, 4, 1)), None
        except BackendError as error:
            return None, str(error)

    def test_json_contract_environment_and_no_key_in_status(self):
        self.reply()
        text, error = self.complete()
        self.assertIsNone(error)
        self.assertIn("ORD-045", text)
        request = self.opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-not-a-real-key")
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertIn("JSON schema", body["messages"][0]["content"])
        self.assertNotIn("test-only-not-a-real-key", json.dumps(backend_status("deepseek")))

    def test_missing_key_is_specific_and_makes_no_call(self):
        os.environ.pop("DEEPSEEK_API_KEY")
        _, error = self.complete()
        self.assertEqual(error, "deepseek_api_key_missing")
        self.opener.open.assert_not_called()

    def test_explicit_backend_wins_over_automatic_detection(self):
        self.assertEqual(default_backend(), "deepseek")
        os.environ["PARSER_BACKEND"] = "offline"
        self.assertEqual(default_backend(), "offline")

    def test_configurable_model_and_timeout(self):
        os.environ.update(DEEPSEEK_MODEL="deepseek-v4-pro", DEEPSEEK_TIMEOUT_SECONDS="12")
        self.reply()
        text, error = self.complete()
        self.assertIsNone(error)
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data)["model"], "deepseek-v4-pro")
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 12)

    def test_bad_configuration_is_not_echoed(self):
        for name, value, expected in (("DEEPSEEK_TIMEOUT_SECONDS", "nan", "deepseek_invalid_timeout"),
                                      ("DEEPSEEK_MODEL", "secret-value", "deepseek_invalid_model"),
                                      ("DEEPSEEK_API_KEY", "bad\nkey", "deepseek_invalid_api_key")):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                _, error = self.complete()
                self.assertEqual(error, expected)
        self.opener.open.assert_not_called()

    def test_http_errors_are_sanitized(self):
        for code in (401, 402, 429, 503):
            with self.subTest(code=code):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(
                    HTTPError("https://api.deepseek.com", code, "secret-provider-body", {},
                              io.BytesIO(b"secret-provider-body")))
                _, error = self.complete()
                self.assertEqual(error, f"deepseek_http_{code}")
                self.assertEqual(self.opener.open.call_count, 1)

    def test_timeout_uses_stable_error(self):
        self.opener.open.side_effect = URLError("secret-provider-body")
        _, error = self.complete()
        self.assertEqual(error, "deepseek_connection_error")

    def test_empty_truncated_and_malformed_responses_are_never_accepted(self):
        for content, reason, expected in (("", "stop", "deepseek_empty_response"),
                                         ("{}", "length", "deepseek_incomplete_output"),
                                         ("{}", "content_filter", "deepseek_refusal")):
            with self.subTest(expected=expected):
                self.reply(content, reason)
                _, error = self.complete()
                self.assertEqual(error, expected)
        self.opener.open.side_effect = None
        self.opener.open.return_value.__enter__.return_value.read.return_value = b"{}"
        _, error = self.complete()
        self.assertEqual(error, "deepseek_invalid_response")

    def test_redirects_do_not_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))


if __name__ == "__main__":
    unittest.main()
