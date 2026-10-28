"""Base model lifetime and native response contracts."""
import unittest

from langchain_core.messages import AIMessage

from app.config.model_settings import load_model_settings
from app.config.model_settings import ModelSpec
from app.llm.errors import BackendError, ModelSelectionError, check_response, check_structured, text_content, translate_error
from app.llm.registry import ModelRegistry
from app.offline.interpreter import interpret
from app.offline.reply import conversational_reply
from app.schemas.chat import TurnInterpretation


class RegistryBehavior(unittest.TestCase):
    def test_compat_chat_llm_calls_use_native_messages(self):
        responses = [AIMessage(content=TurnInterpretation(intent="help_or_chat").model_dump_json(),
                               usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}),
                     AIMessage(content="Hello.", usage_metadata={
                         "input_tokens": 3, "output_tokens": 1, "total_tokens": 4})]

        class Model:
            def invoke(self, messages):
                self.last_messages = messages
                return responses.pop(0)

        class Registry:
            spec = ModelSpec("mock", "openai", "mock", "test")
            model = Model()

            def resolve(self, mode, key):
                return self.spec

            def get_model(self, mode, key):
                return self.model

        registry = Registry()
        context = {"business_date": "2026-04-01", "current_sequence": 1,
                   "history": [], "recent_changes": [], "draft": {}, "recommendation": None}
        value, telemetry = interpret("Hello", context, registry, "llm", "mock")
        self.assertEqual(value.intent, "help_or_chat")
        self.assertEqual(telemetry["usage"]["total_tokens"], 3)
        reply, execution = conversational_reply("Hello", context, registry, "llm", "mock")
        self.assertEqual(reply, "Hello.")
        self.assertEqual(execution["usage"]["total_tokens"], 4)
        self.assertTrue(execution["prompt_hash"])

    def test_config_change_creates_new_model_for_same_alias(self):
        built = []

        def factory(spec):
            model = object()
            built.append((spec.api_model_id, model))
            return model

        first = ModelRegistry(load_model_settings({"OPENAI_API_KEY": "key", "OPENAI_MODEL": "first"}), factory)
        first.initialize()
        original = first.get_model("llm", "openai")
        self.assertIs(original, first.get_model("llm", "openai"))
        second = ModelRegistry(load_model_settings({"OPENAI_API_KEY": "key", "OPENAI_MODEL": "second"}), factory)
        second.initialize()
        self.assertIsNot(original, second.get_model("llm", "openai"))
        self.assertEqual([model_id for model_id, _ in built], ["first", "second"])
        self.assertEqual(first.resolve("llm", "openai").api_model_id, "first")

    def test_default_prompt_and_invalid_structured_methods(self):
        settings = load_model_settings({"DEEPSEEK_API_KEY": "key", "DEEPSEEK_MODEL": "deepseek-chat"})
        self.assertEqual(settings.models[0].output_method, "prompt")
        with self.assertRaises(ValueError):
            load_model_settings({"ANTHROPIC_API_KEY": "key", "ANTHROPIC_MODEL": "claude-test",
                                 "ANTHROPIC_STRUCTURED_OUTPUT": "json_mode"})
        with self.assertRaises(ValueError):
            load_model_settings({"ANTHROPIC_API_KEY": "key", "ANTHROPIC_MODEL": "claude-test",
                                 "ANTHROPIC_STRUCTURED_OUTPUT": "json_schema"})
        with self.assertRaises(ValueError):
            load_model_settings({"DEEPSEEK_API_KEY": "key", "DEEPSEEK_MODEL": "deepseek-reasoner",
                                 "DEEPSEEK_STRUCTURED_OUTPUT": "function_calling"})

    def test_native_tool_ids_usage_and_response_errors(self):
        message = AIMessage(content="", tool_calls=[{"id": "native-1", "name": "look_up", "args": {}}],
                            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
        self.assertIs(check_response(message, require_text=False), message)
        self.assertEqual(message.tool_calls[0]["id"], "native-1")
        self.assertEqual(message.usage_metadata["total_tokens"], 5)
        output_block = AIMessage(content=[{"type": "output_text", "text": "Hello."}])
        self.assertEqual(text_content(check_response(output_block)), "Hello.")
        self.assertEqual(check_structured({"raw": message, "parsed": {"ok": True},
                                           "parsing_error": None})[0], {"ok": True})
        with self.assertRaises(BackendError):
            check_response(AIMessage(content="", response_metadata={"finish_reason": "length"}))
        with self.assertRaises(BackendError):
            check_structured({"raw": message, "parsed": None, "parsing_error": ValueError("bad")})

    def test_missing_model_content_is_an_input_error_even_when_wrapped(self):
        for text in ('contents are required.', 'content is required.', 'content parts are required.'):
            for wrapped in (False, True):
                with self.subTest(text=text, wrapped=wrapped):
                    source = ValueError(text)
                    if wrapped:
                        wrapper = RuntimeError('private outer exception')
                        wrapper.__cause__ = source
                        source = wrapper
                    error = translate_error(source, 'gemini')
                    self.assertEqual(str(error), 'gemini_invalid_input')
                    self.assertFalse(error.retryable)
                    self.assertIsNone(error.upstream_status)
                    self.assertIn('required message content', error.user_message())
                    self.assertNotIn('configuration', error.user_message())
                    self.assertNotIn('End this request', error.user_message())
                    self.assertNotIn('private', str(error.details()))
        self.assertEqual(str(translate_error(ValueError('other error'), 'gemini')), 'gemini_invalid_response')
        generic = BackendError('gemini_invalid_response', retryable=False)
        self.assertNotIn('End this request', generic.user_message())

    def test_selection_and_provider_errors_keep_codes(self):
        registry = ModelRegistry(load_model_settings({"OPENAI_MODELS": '{"openai":"gpt-test"}'}))
        with self.assertRaises(ModelSelectionError) as missing:
            registry.get_model("llm", "openai")
        self.assertEqual(missing.exception.code, "MODEL_NOT_CONFIGURED")
        with self.assertRaises(ModelSelectionError) as unknown:
            registry.resolve("llm", "missing")
        self.assertEqual(unknown.exception.code, "UNKNOWN_MODEL")
        for message, code in ((AIMessage(content=""), "model_empty_response"),
                              (AIMessage(content="no", response_metadata={"finish_reason": "content_filter"}),
                               "model_refusal")):
            with self.subTest(code=code), self.assertRaises(BackendError) as failed:
                check_response(message)
            self.assertEqual(str(failed.exception), code)

        class RateLimit(Exception):
            status_code = 429

        for provider in ("openai", "claude", "gemini", "deepseek"):
            self.assertEqual(str(translate_error(RateLimit(), provider)), provider + "_http_429")
            self.assertTrue(translate_error(RateLimit(), provider).retryable)
            self.assertEqual(str(translate_error(TimeoutError(), provider)),
                             provider + "_connection_error")


if __name__ == "__main__":
    unittest.main()
