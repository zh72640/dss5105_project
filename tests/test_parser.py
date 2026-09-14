import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from app.agent.parser import parse_request, parse_with_telemetry
from app.agent.llm_client import BackendError, LLMBackend
from app.schemas.parser_schema import ParseResult, json_schema


class SequenceBackend:
    name, model, temperature = 'test', 'injected_fake', 0

    def __init__(self, *outputs):
        self.outputs, self.calls = outputs, 0

    def complete(self, message, reference_date, feedback=None):
        value = self.outputs[min(self.calls, len(self.outputs)-1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


class ParserGolden(unittest.TestCase):
    pass


def golden_test(case):
    def test(self):
        self.assertEqual(parse_request(case['message'], backend='offline').to_dict(), case['expected'])
    return test


for case in [json.loads(line) for line in (Path(__file__).parent/'parser_golden.jsonl').read_text().splitlines()]:
    setattr(ParserGolden, 'test_'+case['case_id']+'_'+case['category'], golden_test(case))


class ParserValidation(unittest.TestCase):
    def output(self, **values):
        return json.dumps(ParseResult(order_id='ORD-045', parse_status='ok', **values).to_dict())

    def test_retry_once_then_success(self):
        backend=SequenceBackend('{broken',self.output())
        out=parse_with_telemetry('Allocate ORD-045.',backend=backend)
        self.assertEqual(out.parsed.order_id,'ORD-045'); self.assertEqual(backend.calls,2)
        self.assertEqual(out.telemetry['retry_count'],1)
        self.assertIsNone(out.telemetry['attempts'][0]['validated_output'])

    def test_twice_invalid_stops(self):
        backend=SequenceBackend('{}')
        out=parse_with_telemetry('Allocate ORD-045.',backend=backend)
        self.assertIsNone(out.parsed); self.assertEqual(backend.calls,2)

    def test_transient_transport_retry(self):
        backend=SequenceBackend(BackendError('llm_http_429'),self.output())
        self.assertIsNotNone(parse_with_telemetry('Allocate ORD-045.',backend=backend).parsed)
        self.assertEqual(backend.calls,2)

    def test_permanent_transport_no_retry(self):
        backend=SequenceBackend(BackendError('llm_http_401',False))
        self.assertIsNone(parse_with_telemetry('Allocate ORD-045.',backend=backend).parsed)
        self.assertEqual(backend.calls,1)

    def test_hallucinated_fields_rejected(self):
        for values in ({'pieces':150},{'due_date':'2026-04-09'},{'num_workshop_allowed':2},
                       {'customer':'Cotton Club'},{'category':'TOPS'},{'exclusion':['W3']}, {'objective':'min_cost'}):
            with self.subTest(values=values):
                self.assertIsNone(parse_with_telemetry('Allocate ORD-045.',backend=SequenceBackend(self.output(**values))).parsed)
        self.assertIsNone(parse_with_telemetry('Allocate the order.',backend=SequenceBackend(self.output())).parsed)

    def test_dropped_exclusion_rejected(self):
        self.assertIsNone(parse_with_telemetry('Allocate ORD-045; exclude W3.',backend=SequenceBackend(self.output())).parsed)

    def test_boolean_number_unknown_fields_duplicate_keys_rejected(self):
        for raw in (self.output(pieces=True),self.output().replace('"pieces": null','"pieces": 2.5'),
                    self.output()[:-1]+',"decision":"ALLOCATE"}',self.output()[:-1]+',"pieces":null}'):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_with_telemetry('Allocate ORD-045.',backend=SequenceBackend(raw)).parsed)

    def test_session_extension_fails_closed(self):
        out=parse_with_telemetry('Allocate ORD-045.',context_messages=[{'role':'user','content':'hi'}])
        self.assertEqual(out.error,'context_not_supported')

    def test_reference_year_is_explicit(self):
        self.assertEqual(parse_request('Allocate ORD-045 due Apr 09.',reference_date=date(2027,4,1),backend='offline').due_date,'2027-04-09')

    def test_unrecognized_constraints_and_negative_action_stop(self):
        for text in ('Allocate ORD-045 with budget 100.','Allocate ORD-045 to MysteryShop.', 'Do not allocate ORD-045.'):
            self.assertNotEqual(parse_request(text,backend='offline').parse_status,'ok')

    def test_other_providers_keys_are_not_used(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY':'test-only','GOOGLE_API_KEY':'test-only','LLM_API_KEY':'test-only'}, clear=True):
            out = parse_with_telemetry('Allocate ORD-045.', backend='llm')
        self.assertEqual(out.error, 'gemini_api_key_missing')
        self.assertEqual(out.telemetry['provider'], 'google_gemini')
        self.assertEqual(out.telemetry['model'], 'gemini-2.5-flash')

    def test_llm_missing_config_fails_without_fallback(self):
        with patch.dict('os.environ',{},clear=True):
            out=parse_with_telemetry('Allocate ORD-045.',backend='llm')
        self.assertEqual(out.error,'gemini_api_key_missing'); self.assertIsNone(out.parsed)
