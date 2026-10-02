"""Acceptance reports must distinguish service failures from model output."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from app.agent.parser import ParserOutcome
from app.schemas.parser_schema import ParseResult
from evaluation.evaluate_parser import evaluate


class EvaluationTests(unittest.TestCase):
    def test_rate_limit_failures_remain_in_acceptance_denominator(self):
        cases = [json.loads(line) for line in (Path(__file__).parent / 'parser_golden.jsonl').read_text().splitlines()]
        outcomes = []
        for index, case in enumerate(cases):
            parsed = ParseResult(**case['expected']) if index < 14 else None
            error = None if parsed else 'gemini_http_429'
            outcomes.append(ParserOutcome(parsed, {'model': 'test-model', 'latency_ms': 1, 'attempts': [
                {'raw_output': json.dumps(case['expected']) if parsed else None,
                 'validated_output': case['expected'] if parsed else None, 'error': error}]}, error))
        with patch('evaluation.evaluate_parser.parse_with_telemetry', side_effect=outcomes), patch('evaluation.evaluate_parser.time.sleep') as sleep:
            metrics, _ = evaluate('llm', 2)
        self.assertFalse(metrics['live_llm_validated'])
        self.assertEqual(metrics['passed_cases'], 14)
        self.assertEqual(metrics['cases_with_model_output'], 14)
        self.assertEqual(metrics['error_counts'], {'gemini_http_429': 46})
        self.assertEqual(metrics['core_field_exact_match'], 14/60)
        self.assertEqual(sleep.call_count, 59)

    def test_invalid_pacing_rejected_before_model_calls(self):
        for value in (-1, 61, float('nan'), float('inf')):
            with self.subTest(value=value), patch('evaluation.evaluate_parser.parse_with_telemetry') as parse:
                with self.assertRaises(ValueError):
                    evaluate('llm', value)
                parse.assert_not_called()
