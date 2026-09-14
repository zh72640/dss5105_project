"""Real Google SDK serialization/error handling over httpx.MockTransport; no live calls."""
import importlib.util
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from app.agent.parser import parse_with_telemetry
from app.agent.llm_client import gemini_json_schema
from app.schemas.parser_schema import ParseResult, json_schema

try:
    SDK_AVAILABLE = importlib.util.find_spec('google.genai') is not None
except ModuleNotFoundError:
    SDK_AVAILABLE = False


@unittest.skipUnless(SDK_AVAILABLE, 'Install requirements.txt for Google SDK integration tests')
class GeminiSDK(unittest.TestCase):
    def setUp(self):
        import httpx
        from google import genai
        self.httpx = httpx
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict('os.environ', {
            'GEMINI_API_KEY': 'gemini-test-key-not-a-secret', 'GOOGLE_API_KEY': 'must-not-use',
            'LLM_API_KEY': 'must-not-use', 'LLM_MODEL': 'must-not-use',
            'GOOGLE_GENAI_USE_VERTEXAI': 'true', 'GOOGLE_GEMINI_BASE_URL': 'https://must-not-use.invalid',
        }, clear=True))
        self.calls, self.clients, self.options, self.sdk_closes = [], [], [], []
        self.responses = [(200, self.body())]
        actual_client = genai.Client
        def construct(**kwargs):
            self.options.append(kwargs)
            http_client = httpx.Client(transport=httpx.MockTransport(self.respond))
            self.stack.callback(http_client.close)
            self.clients.append(http_client)
            kwargs['http_options'].httpx_client = http_client
            client = actual_client(**kwargs)
            self.sdk_closes.append(self.stack.enter_context(patch.object(client, 'close', wraps=client.close)))
            return client
        self.stack.enter_context(patch('google.genai.Client', side_effect=construct))

    def body(self, text=None, finish='STOP'):
        if text is None:
            text = json.dumps(ParseResult(order_id='ORD-045', parse_status='ok').to_dict())
        return {'candidates': [{'content': {'role': 'model', 'parts': [{'text': text}]}, 'finishReason': finish}]}

    def respond(self, request):
        self.calls.append(request)
        response = self.responses[min(len(self.calls)-1, len(self.responses)-1)]
        if isinstance(response, Exception):
            raise response
        status, body = response
        return self.httpx.Response(status, json=body)

    def parse(self):
        return parse_with_telemetry('Allocate ORD-045.', backend='llm')

    def test_official_endpoint_key_model_and_schema(self):
        out = self.parse()
        self.assertEqual(out.parsed.order_id, 'ORD-045')
        request = self.calls[0]
        self.assertEqual(str(request.url), 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent')
        self.assertEqual(request.headers['x-goog-api-key'], 'gemini-test-key-not-a-secret')
        data = json.loads(request.content)
        config = data['generationConfig']
        self.assertEqual(config['responseMimeType'], 'application/json')
        self.assertEqual(config['responseJsonSchema'], gemini_json_schema())
        self.assertEqual(config['temperature'], 0)
        thinking = config['thinkingConfig']
        self.assertEqual(thinking.get('thinkingBudget', thinking.get('thinking_budget')), 0)
        self.assertIn('Reference date: 2026-04-01', data['systemInstruction']['parts'][0]['text'])
        self.assertEqual(data['contents'][-1]['parts'][0]['text'], 'Allocate ORD-045.')
        self.assertEqual([m['role'] for m in data['contents']], ['user','model']*4+['user'])
        self.assertEqual(self.options[0]['http_options'].retry_options.attempts, 1)
        self.assertEqual(self.options[0]['http_options'].timeout, 30000)
        self.assertIs(self.options[0]['vertexai'], False)
        self.assertTrue(all(close.call_count == 1 for close in self.sdk_closes))
        self.assertNotIn('gemini-test-key-not-a-secret', json.dumps(out.telemetry))

    def test_429_retries_once_in_parser(self):
        self.responses = [(429, {'error': {'code': 429, 'message': 'rate limited'}}), (200, self.body())]
        out = self.parse()
        self.assertIsNotNone(out.parsed); self.assertEqual(len(self.calls), 2)
        self.assertEqual(out.telemetry['retry_count'], 1)
        second = json.loads(self.calls[1].content)
        self.assertIn('gemini_http_429', second['systemInstruction']['parts'][0]['text'])

    def test_persistent_503_has_two_calls_total(self):
        self.responses = [(503, {'error': {'code': 503, 'message': 'unavailable'}})]
        self.assertEqual(self.parse().error, 'gemini_http_503')
        self.assertEqual(len(self.calls), 2)

    def test_auth_error_no_retry_and_no_body_leak(self):
        self.responses = [(403, {'error': {'code': 403, 'message': 'private service detail'}})]
        out = self.parse()
        self.assertEqual(out.error, 'gemini_http_403'); self.assertEqual(len(self.calls), 1)
        self.assertNotIn('private service detail', json.dumps(out.telemetry))

    def test_blocked_prompt_stops(self):
        self.responses = [(200, {'promptFeedback': {'blockReason': 'SAFETY'}})]
        self.assertEqual(self.parse().error, 'gemini_refusal'); self.assertEqual(len(self.calls), 1)

    def test_truncated_output_is_not_allocated(self):
        self.responses = [(200, self.body(finish='MAX_TOKENS'))]
        self.assertEqual(self.parse().error, 'gemini_incomplete_output'); self.assertEqual(len(self.calls), 2)

    def test_invalid_json_retry_then_validated(self):
        self.responses = [(200, self.body(text='{broken')), (200, self.body())]
        out = self.parse()
        self.assertIsNotNone(out.parsed); self.assertEqual(len(self.calls), 2)
        self.assertEqual(out.telemetry['attempts'][0]['error'], 'invalid_json')

    def test_timeout_error_is_bounded(self):
        self.responses = [self.httpx.ReadTimeout('do not log this service detail')]
        out = self.parse()
        self.assertEqual(out.error, 'gemini_connection_error'); self.assertEqual(len(self.calls), 2)

    def test_empty_response_is_rejected(self):
        self.responses = [(200, {})]
        self.assertEqual(self.parse().error, 'gemini_empty_response'); self.assertEqual(len(self.calls), 2)

    def test_wire_nullable_enums_preserve_parser_contract(self):
        schema = gemini_json_schema()
        for field in ('objective', 'category'):
            self.assertEqual(schema['properties'][field]['anyOf'][1], {'type': 'null'})
            self.assertEqual(schema['properties'][field]['anyOf'][0]['enum'], [v for v in json_schema()['properties'][field]['enum'] if v is not None])
        self.assertEqual(schema['required'], json_schema()['required'])
        self.assertFalse(schema['additionalProperties'])
