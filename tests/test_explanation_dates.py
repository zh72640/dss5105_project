"""Date wording must not bypass fact checks or trigger numeric false positives."""
from copy import deepcopy
import unittest

from app.services.chat.explanation_guard import claim_problem


class ExplanationDateChecks(unittest.TestCase):
    def setUp(self):
        self.payload = {'order_id': 'ORD-066', 'objective': 'min_delay', 'pieces': 1000,
            'due_date': '2026-04-15', 'estimated_delivery_date': '2026-04-10',
            'delay_days': -5, 'estimated_cost': 1500, 'expected_defect_rate': .12}

    def test_equivalent_date_formats_pass_without_allowing_standalone_date_numbers(self):
        for value in ('2026-04-10', 'April 10, 2026', 'April 10 2026', 'Apr 10, 2026',
                      'Apr. 10, 2026', '10 April 2026', '10 Apr. 2026', 'APRIL 10, 2026',
                      'April 10th, 2026', '10th April 2026'):
            with self.subTest(value=value):
                self.assertIsNone(claim_problem('Estimated completion is ' + value + '.', self.payload))
        self.assertEqual(claim_problem('The quoted cost is 2026.', self.payload), 'unsupported_number')
        self.assertEqual(claim_problem('Estimated completion April 10, 2026; cost 2026.', self.payload),
                         'unsupported_number')

    def test_saved_completion_and_due_date_can_both_use_english(self):
        self.assertIsNone(claim_problem(
            'Estimated completion April 10, 2026; due April 15, 2026; cost 1,500; expected defects 12%.',
            self.payload))

    def test_wrong_dates_are_rejected_even_if_their_day_is_an_allowed_number(self):
        for value in ('April 5, 2026', 'April 10, 2027', 'May 10, 2026',
                      '2026-04-05', '5 April 2026'):
            with self.subTest(value=value):
                self.assertEqual(claim_problem('Estimated completion ' + value + '.', self.payload),
                                 'unsupported_date')

    def test_invalid_calendar_dates_are_rejected(self):
        for value in ('April 31, 2026', 'February 29, 2026', '2026-02-30', '31 April 2026'):
            with self.subTest(value=value):
                self.assertEqual(claim_problem('Estimated completion ' + value + '.', self.payload),
                                 'unsupported_date')

    def test_one_valid_date_does_not_hide_an_invented_second_date(self):
        self.assertEqual(claim_problem('Completion April 10, 2026; due April 5, 2026.', self.payload),
                         'unsupported_date')

    def test_yearless_date_requires_one_saved_match(self):
        for value in ('April 10', '10 April', 'Apr. 10', 'April 10th'):
            with self.subTest(value=value):
                self.assertIsNone(claim_problem('Estimated completion ' + value + '.', self.payload))
        self.assertEqual(claim_problem('Estimated completion April 5.', self.payload), 'unsupported_date')
        ambiguous = {**self.payload, 'another_date': '2027-04-10'}
        self.assertEqual(claim_problem('Estimated completion April 10.', ambiguous), 'unsupported_date')

    def test_unknown_due_date_still_allows_a_verified_completion_date(self):
        payload = {**self.payload, 'due_date': None, 'delay_days': None}
        self.assertIsNone(claim_problem(
            'Estimated completion April 10, 2026. No confirmed due date is available.', payload))
        self.assertEqual(claim_problem('The due date is April 15, 2026.', payload), 'unsupported_date')

    def test_other_fact_checks_and_payload_are_preserved(self):
        original = deepcopy(self.payload)
        self.assertEqual(claim_problem('Completion April 10, 2026; estimated cost 1600.', self.payload),
                         'unsupported_number')
        self.assertEqual(claim_problem('Recommend W99; completion April 10, 2026.', self.payload),
                         'unsupported_identifier')
        self.assertEqual(claim_problem('Completion April 10, 2026; we guarantee delivery.', self.payload),
                         'unverified_guarantee')
        self.assertEqual(self.payload, original)

    def test_all_month_names_and_abbreviations_are_calendar_checked(self):
        names = ('January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December')
        for month, name in enumerate(names, 1):
            payload = {**self.payload, 'estimated_delivery_date': f'2026-{month:02d}-10'}
            for label in (name, name[:3]):
                with self.subTest(label=label):
                    self.assertIsNone(claim_problem(f'Completion {label} 10, 2026.', payload))
        september = {**self.payload, 'estimated_delivery_date': '2026-09-10'}
        self.assertIsNone(claim_problem('Completion Sept. 10, 2026.', september))
