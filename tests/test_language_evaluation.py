"""Evaluation failures stay in denominators and never imply successful writes."""
import unittest
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.config.model_settings import ModelSettings, ModelSpec
from app.services.chat.service import ChatError
from evaluation.evaluate_chat_language import evaluate, original_cases
from evaluation import verify_gemini_live


class LanguageEvaluation(unittest.TestCase):
    def test_original_inbox_is_complete_without_dataset_labels_in_messages(self):
        cases = original_cases()
        self.assertEqual(len(cases), 30)
        self.assertEqual(cases[0]['id'], 'R01')
        self.assertFalse(cases[0]['message'].startswith('R01'))

    def test_service_failure_counts_in_accuracy_and_field_denominators(self):
        cases = [{'id': 'one', 'message': 'Allocate ORD-045.', 'expected_behavior': 'ALLOCATE',
                  'expected_fields': {'order_id': 'ORD-045'}},
                 {'id': 'two', 'message': 'Allocate ORD-109.', 'expected_behavior': 'ALLOCATE',
                  'expected_fields': {'order_id': 'ORD-109'}}]
        success = {'committed': False, 'session': {'recommendation': {'status': 'valid'},
                   'task': {'draft': {'order_id': 'ORD-045'}}}, 'assistant_message': {'content': 'Review first.'}}
        with patch('evaluation.evaluate_chat_language.chat.create',
                   side_effect=[success, ChatError('MODEL_UNAVAILABLE', 'Unavailable', 503)]):
            summary, records = evaluate(cases, mode='llm', registry=object())
        self.assertEqual(summary['cases'], 2)
        self.assertEqual(summary['service_success_rate'], .5)
        self.assertEqual(summary['behavior_accuracy_all_cases'], .5)
        self.assertEqual(summary['field_accuracy_all_labelled_slots'], .5)
        self.assertEqual(summary['explanation_reviews_completed'], 0)
        self.assertEqual(records[1]['actual_behavior'], 'SERVICE_ERROR')
        self.assertEqual(summary['production_rows_written'], 0)

    def test_offline_real_intake_uses_an_isolated_database_per_case(self):
        cases = [{'id': str(n), 'message': 'Allocate ORD-045.', 'expected_behavior': 'ALLOCATE'} for n in range(2)]
        summary, records = evaluate(cases, mode='offline')
        self.assertEqual(summary['behavior_matches'], 2)
        self.assertEqual(summary['production_rows_written'], 0)
        self.assertTrue(all(row['explanation_review'] is None for row in records))

    def test_gemini_smoke_selects_gemini_and_does_not_pass_a_blocked_response(self):
        settings = ModelSettings(default_model='other', models=(
            ModelSpec('other', 'openai', 'test-other', 'test'),
            ModelSpec('gemini-test', 'gemini', 'test-gemini', 'test')))
        for response, expected in (({'task_state': 'BLOCKED', 'session': {}}, 1),
                                   ({'task_state': 'RECOMMENDED', 'session': {'recommendation': {'status': 'valid'}}}, 0)):
            with self.subTest(state=response['task_state']), tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}, clear=True), \
                     patch.object(verify_gemini_live, 'load_model_settings', return_value=settings), \
                     patch.object(verify_gemini_live, 'ModelRegistry') as registry, \
                     patch.object(verify_gemini_live.chat, 'create', return_value=response) as create, \
                     patch('sys.argv', ['verify', '--output-dir', directory]), redirect_stdout(io.StringIO()):
                    self.assertEqual(verify_gemini_live.main(), expected)
                    self.assertEqual(create.call_args.kwargs['model_key'], 'gemini-test')
                    self.assertIs(create.call_args.kwargs['registry'], registry.return_value)
                    registry.return_value.close.assert_called_once()
                report = json.loads((Path(directory) / 'gemini_live_summary.json').read_text())
                self.assertEqual(report['status'], 'SMOKE_PASSED' if expected == 0 else 'SMOKE_FAILED')
