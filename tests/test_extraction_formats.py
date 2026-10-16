"""Model JSON wrappers and grounded short order references; no live provider calls."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from app.llm.json_output import json_text
from app.services.chat import service as chat
from app.services.intake.normalization import order_ids
from tests.test_allocation_node import ExtractionScript, actions
from tests.test_architecture_alignment import NativeScript


class JsonOutputBehavior(unittest.TestCase):
    def test_only_whole_json_fences_are_unwrapped(self):
        for text in ('{"a":1}', '```json\n{"a":1}\n```', '```JSON\r\n{"a":1}\r\n```',
                     '  ```\n{"a":1}\n```\n'):
            with self.subTest(text=text):
                self.assertEqual(json.loads(json_text(text)), {'a': 1})
        for text in ('Before ```json\n{"a":1}\n```', '```json\n{"a":1}\n``` After',
                     '```python\n{"a":1}\n```', '```json\n{"a":1\n```',
                     '```json\n{"a":1}\n```\n```json\n{"b":2}\n```'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                json.loads(json_text(text))

    def test_short_ids_are_opt_in_evidence_normalization(self):
        for text in ('order 45', 'order #45', 'order ID 45', 'Order number 45.', 'order no. 045'):
            with self.subTest(text=text):
                self.assertEqual(order_ids(text), [])
                self.assertEqual(order_ids(text, allow_short=True), ['ORD-045'])
        for text in ('45 pieces', '45', 'order -45', 'order 45.5', 'order 4500', 'order 45-46'):
            with self.subTest(text=text):
                self.assertEqual(order_ids(text, allow_short=True), [])
        self.assertEqual(order_ids('ORD-045 and O45', allow_short=True), ['ORD-045', 'O45'])


class ExtractionBoundaryBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'extraction.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
                               as_of=date(2026, 4, 1), mode='llm')['session_id']

    def turn(self, model, text='allocate order 45'):
        return chat.turn(self.sid, owner='alice', request_id='allocate', expected_version=0,
                         db_path=self.path, registry=model, message=text)

    def validation_events(self):
        trace = chat.execution_trace(self.sid, owner='alice', db_path=self.path)
        return [event['detail'] for event in trace['events']
                if event['event_type'] == 'extraction_validation_failed']

    def test_fenced_llm_extraction_of_short_id_reaches_saved_recommendation(self):
        class Fenced(NativeScript):
            def invoke_task(self, mode, key, bundle):
                result, metadata = super().invoke_task(mode, key, bundle)
                result['text'] = '```json\n' + result['text'] + '\n```'
                return result, metadata
        model = Fenced(actions=actions(), intent_text='```json\n{"task_type":"allocation"}\n```')
        result = self.turn(model)
        self.assertEqual(result['allocation']['order_id'], 'ORD-045')
        self.assertEqual(result['allocation']['pieces'], 150)
        self.assertIsNotNone(result['recommendation_id'])
        self.assertTrue(model.preparation_prompts)
        self.assertEqual(self.validation_events(), [])

    def test_quantity_is_not_mistaken_for_an_order_id(self):
        result = self.turn(NativeScript(), 'allocate 45 pieces')
        self.assertIsNone(result['allocation'])
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_EVIDENCE_INVALID')
        self.assertEqual(self.validation_events()[0]['reason'], 'UNGROUNDED_ORDER')

    def test_different_id_is_rejected_even_when_a_short_reference_is_present(self):
        result = self.turn(NativeScript(order_id='ORD-046'))
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_EVIDENCE_INVALID')

    def test_invalid_field_types_remain_format_errors_with_diagnostic_locations(self):
        result = self.turn(NativeScript(order_id=45))
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_FORMAT_INVALID')
        detail = self.validation_events()[0]
        self.assertEqual(detail['stage'], 'format')
        self.assertEqual(detail['errors'][0]['location'], ['order_id'])
        self.assertEqual(detail['errors'][0]['type'], 'string_type')
        self.assertNotIn('input', detail['errors'][0])

    def test_bad_json_inside_a_fence_is_not_repaired(self):
        result = self.turn(ExtractionScript(malformed='```json\n{"intent":"allocate_request"\n```'))
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_FORMAT_INVALID')
        self.assertEqual(self.validation_events()[0]['errors'][0]['type'], 'json_invalid')
