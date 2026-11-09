"""Optional split notices preserve normal previews and unrelated business blockers."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.db import chat_repository
from app.db.database import Database
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import ExtractionValidationError, validate_candidate
from tests.test_allocation_node import actions
from tests.test_workshop_assignment_intake import AssignmentScript

MESSAGE = 'ORD-005 — 500 scarves for TrendCart, due Apr 20. Split it across two shops if that gets it back faster.'
REASON = 'The request to split the order across two shops is an unsupported exact-split requirement.'
GENERIC = 'This requirement cannot be computed: budget cap, exact split, or quality threshold. Withdraw it or use an existing business workflow.'


def candidate(legacy=False):
    """Replay the reported extraction or the new specific optional category."""
    return {'intent': 'allocate_request', 'patch_operations': [
        {'op': 'set', 'field': 'order_id', 'value': 'ORD-005', 'quote': 'ORD-005'},
        {'op': 'set', 'field': 'pieces', 'value': 500, 'quote': '500 scarves'},
        {'op': 'set', 'field': 'product', 'value': 'Scarf', 'quote': 'scarves'},
        {'op': 'set', 'field': 'customer', 'value': 'TrendCart', 'quote': 'TrendCart'},
        {'op': 'set', 'field': 'due_date', 'value': '2026-04-20', 'quote': 'due Apr 20'}],
        'unsupported_constraints': ['unsupported_constraint' if legacy else 'optional_split'],
        'ambiguity_reason': REASON if legacy else None}


class OptionalSplitIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'optional.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
                               as_of=date(2026, 4, 1), mode='llm')['session_id']
        with Database(self.path) as db:
            self.context = build_context(db.connection, chat_repository.snapshot(db.connection, self.sid, 'alice'))

    def run_request(self, value, text=MESSAGE, request_id='allocate', version=0):
        model = AssignmentScript([value], actions=actions())
        args = dict(owner='alice', request_id=request_id, expected_version=version,
                    db_path=self.path, message=text, registry=model)
        return chat.turn(self.sid, **args), model, args

    def assert_preview_with_notice(self, response):
        self.assertIsNotNone(response['recommendation_id'])
        self.assertEqual(response['allocation']['order_id'], 'ORD-005')
        self.assertEqual(response['allocation']['allocated_pieces'], 500)
        self.assertEqual(response['session']['task']['report']['effective_constraints']['num_workshop_allowed'], 1)
        self.assertEqual(response['session']['task']['issues'], [])
        self.assertEqual(response['session']['task']['report']['blocking_issues'], [])
        self.assertEqual(response['issues'][0]['code'], 'OPTIONAL_SPLIT_NOT_APPLIED')
        self.assertEqual(response['issues'][0]['severity'], 'warning')
        text = response['assistant_message']['content']
        self.assertEqual(text.count(REASON), 1)
        self.assertIn('does not apply that split request', text)
        self.assertNotIn('Withdraw it', text)
        self.assertFalse(response['committed'])

    def test_saved_real_extraction_now_creates_preview_and_replays(self):
        response, model, args = self.run_request(candidate(legacy=True))
        self.assert_preview_with_notice(response)
        self.assertEqual(model.extractions, 1)
        replay = chat.turn(self.sid, **args)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'], response['recommendation_id'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_specific_optional_category_survives_all_tools_and_explanation_fallback(self):
        response, model, _ = self.run_request(candidate())
        self.assert_preview_with_notice(response)
        self.assertEqual(len(model.offered), 3)
        notice = response['session']['task']['report']['allocation_notices'][0]
        self.assertEqual(notice['quote'], 'Split it across two shops if that gets it back faster.')
        self.assertEqual(notice['message_sequence'], 1)

    def test_new_revision_keeps_the_unapplied_split_disclosure(self):
        first, _, _ = self.run_request(candidate())
        change = {'intent': 'modify_constraints', 'patch_operations': [
            {'op': 'set', 'field': 'objective', 'value': 'min_cost', 'quote': 'lowest cost'}]}
        second, _, _ = self.run_request(change, 'Use lowest cost.', 'revise', first['session_version'])
        self.assert_preview_with_notice(second)
        self.assertEqual(second['allocation']['objective'], 'min_cost')

    def test_unrelated_budget_is_not_relaxed_by_the_legacy_split_fallback(self):
        response, model, _ = self.run_request(candidate(legacy=True), MESSAGE + ' Budget under 100.')
        self.assertIsNone(response['recommendation_id'])
        self.assertTrue(any(i['code'] == 'unsupported_constraint' for i in response['issues']))
        self.assertFalse(model.offered)

    def test_explicit_optional_and_hard_constraint_categories_remain_separate(self):
        value = candidate()
        value['unsupported_constraints'].append('unsupported_constraint')
        value['ambiguity_reason'] = 'The budget cap cannot be enforced.'
        response, model, _ = self.run_request(value, MESSAGE + ' Budget under 100.')
        self.assertIsNone(response['recommendation_id'])
        self.assertTrue(any(i['code'] == 'unsupported_constraint' for i in response['issues']))
        self.assertEqual(len(response['session']['task']['report']['allocation_notices']), 1)
        self.assertFalse(model.offered)

    def test_optional_category_cannot_hide_a_stated_budget_requirement(self):
        with self.assertRaises(ExtractionValidationError) as caught:
            validate_candidate(candidate(), message=MESSAGE + ' Budget under 100.', conversation=self.context)
        self.assertEqual(caught.exception.detail['reason'], 'OMITTED_HARD_UNSUPPORTED_REQUIREMENT')

    def test_hard_or_negated_splits_cannot_use_the_optional_category(self):
        for text in (MESSAGE.replace('if that gets it back faster', 'exactly as specified'),
                     MESSAGE.replace('Split it', 'Do not split it'),
                     MESSAGE.replace('Split it', 'You must split it')):
            with self.subTest(text=text), self.assertRaises(ExtractionValidationError):
                validate_candidate(candidate(), message=text, conversation=self.context)

    def test_optional_clause_cannot_silently_change_the_workshop_limit(self):
        for quote in ('two shops', MESSAGE):
            value = candidate()
            value['patch_operations'].append({'op': 'set', 'field': 'num_workshop_allowed', 'value': 2, 'quote': quote})
            with self.subTest(quote=quote), self.assertRaises(ExtractionValidationError) as caught:
                validate_candidate(value, message=MESSAGE, conversation=self.context)
            self.assertEqual(caught.exception.detail['reason'], 'OPTIONAL_SPLIT_MUST_NOT_SET_WORKSHOP_LIMIT')

    def test_missing_order_still_requires_clarification(self):
        value = candidate()
        value['patch_operations'].pop(0)
        text = MESSAGE.replace('ORD-005 — ', '')
        response, model, _ = self.run_request(value, text)
        self.assertIsNone(response['recommendation_id'])
        self.assertTrue(any(i['code'] == 'MISSING_ORDER_ID' for i in response['issues']))
        self.assertFalse(model.offered)
        answer = {'intent': 'answer_clarification', 'patch_operations': [
            {'op': 'set', 'field': 'order_id', 'value': '5', 'quote': 'ord 5'}]}
        resumed, _, _ = self.run_request(answer, 'ord 5', 'answer', response['session_version'])
        self.assert_preview_with_notice(resumed)

    def test_saved_isolated_false_refusal_recovers_on_new_optional_authorization(self):
        with Database(self.path) as db, db.transaction() as connection:
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['issues'] = [
                {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'severity': 'blocking', 'question': REASON},
                {'code': 'unsupported_constraint', 'field': 'unsupported', 'severity': 'blocking', 'question': GENERIC}]
            chat_repository.save_task(connection, session['task'])
        response, _, _ = self.run_request(candidate())
        self.assert_preview_with_notice(response)

    def test_legacy_recovery_does_not_remove_additional_saved_requirements(self):
        with Database(self.path) as db, db.transaction() as connection:
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['issues'] = [
                {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'severity': 'blocking', 'question': REASON},
                {'code': 'unsupported_constraint', 'field': 'unsupported', 'severity': 'blocking', 'question': GENERIC},
                {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'severity': 'blocking', 'question': 'Clarify the budget cap.'}]
            chat_repository.save_task(connection, session['task'])
        response, model, _ = self.run_request(candidate())
        self.assertIsNone(response['recommendation_id'])
        self.assertTrue(any(i['question'] == 'Clarify the budget cap.' for i in response['issues']))
        self.assertFalse(model.offered)


if __name__ == '__main__':
    unittest.main()
