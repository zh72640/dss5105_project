"""The evaluation entry point uses current APIs without a production database."""
import unittest

from run_clarification_eval import environment, evaluate


class CurrentIntakeEvaluation(unittest.TestCase):
    def test_queries_missing_references_and_complete_requests_have_distinct_labels(self):
        with environment('offline') as (db, registry, spec):
            for key, text, status in (
                ('query', 'Any movement on ORD-999? Customer is chasing.', 'invalid'),
                ('missing', 'Can we get the TrendCart order moving? They are chasing.', 'needs_clarification'),
                ('complete', 'Allocate ORD-109 due Apr 13.', 'ok'),
            ):
                with self.subTest(key=key):
                    predicted, _, error = evaluate(text, key, 'offline', 'intake', db, registry, spec)
                    self.assertEqual(predicted, status)
                    self.assertIsNone(error)
