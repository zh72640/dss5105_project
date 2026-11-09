"""Partial facts and abbreviated order replies use scripted models and isolated data."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from app.db import chat_repository
from app.db.database import Database
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import ExtractionValidationError, validate_candidate
from app.services.chat.interpretation import rule_interpret
from app.services.intake.normalization import order_ids
from tests.test_allocation_node import actions
from tests.test_order_selection import SelectionScript
from tests.test_workshop_assignment_intake import AssignmentScript

MESSAGE = 'Need scarves for Harbor Knits sent out today, usual quantities.'
QUESTION = 'The order reference is needed to identify the usual quantity for the scarves.'
EMPTY = {'intent': 'unsupported_or_ambiguous', 'patch_operations': [], 'ambiguity_reason': QUESTION}
FACTS = {'intent': 'allocate_request', 'patch_operations': [
    {'op': 'set', 'field': 'product', 'value': 'Scarf', 'quote': 'scarves'},
    {'op': 'set', 'field': 'customer', 'value': 'Harbor Knits', 'quote': 'Harbor Knits'}]}


class PartialOrderIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'partial.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
                               as_of=date(2026, 4, 1), mode='llm')['session_id']
        with Database(self.path) as db:
            self.context = build_context(db.connection, chat_repository.snapshot(db.connection, self.sid, 'alice'))

    def test_product_omission_is_rejected_even_without_an_order_id(self):
        with self.assertRaises(ExtractionValidationError) as caught:
            validate_candidate(EMPTY, message=MESSAGE, conversation=self.context)
        self.assertEqual(caught.exception.detail['reason'], 'OMITTED_EXPLICIT_PRODUCT')
        self.assertEqual(caught.exception.detail['expected_value'], 'Scarf')

    def test_ambiguous_or_readonly_product_mentions_do_not_force_patches(self):
        for message, intent in [('Can we make scarves or vests?', 'unsupported_or_ambiguous'),
                                ('What is the status of scarves?', 'query_order'),
                                ('If we need scarves, what happens?', 'unsupported_or_ambiguous'),
                                ('Not scarves.', 'unsupported_or_ambiguous')]:
            with self.subTest(message=message):
                result = validate_candidate({'intent': intent}, message=message, conversation=self.context)
                self.assertEqual(result.patch_operations, [])

    def test_common_ord_spellings_normalize_but_quantities_and_dates_do_not(self):
        for quote in ('ord 34', 'ORD 034', 'ORD-34', 'ord-034', 'order 34'):
            for value in ('34', 'ORD-034', quote):
                with self.subTest(quote=quote, value=value):
                    result = validate_candidate({'intent': 'answer_clarification', 'patch_operations': [
                        {'op': 'set', 'field': 'order_id', 'value': value, 'quote': quote}]},
                        message=quote, conversation=self.context)
                    self.assertEqual(result.patch_operations[0].value, 'ORD-034')
                    self.assertEqual(result.patch_operations[0].evidence.quote, quote)
        for quote in ('34', '34 scarves', 'ORD-0345', 'ord 34.5', 'ord 34/35'):
            self.assertEqual(order_ids(quote, allow_short=True), [])
        self.assertEqual(order_ids('ord 34, 300 scarves', allow_short=True), ['ORD-034'])
        self.assertEqual(order_ids('ord 34 and 35', allow_short=True), ['ORD-034', 'ORD-035'])

    def test_abbreviated_reply_to_a_status_question_stays_read_only(self):
        context = deepcopy(self.context)
        context['history'] = [{'role': 'user', 'content': 'What is the order status?'},
                              {'role': 'assistant', 'content': 'Provide a valid order ID.'}]
        result = rule_interpret('ord 34', context)
        self.assertEqual(result.intent, 'query_order')
        self.assertEqual(result.referenced_order_id, 'ORD-034')
        self.assertEqual(result.patch_operations, [])

    def test_normalization_cannot_replace_a_different_order_or_unlabeled_number(self):
        for quote, value in [('ord 34', '35'), ('ord 34', 'ORD-035'), ('34 scarves', '34')]:
            with self.subTest(quote=quote, value=value), self.assertRaises(ExtractionValidationError):
                validate_candidate({'intent': 'answer_clarification', 'patch_operations': [
                    {'op': 'set', 'field': 'order_id', 'value': value, 'quote': quote}]},
                    message=quote, conversation=self.context)

    def test_answered_marker_requires_all_ambiguities_to_be_scoped_and_answered(self):
        context = deepcopy(self.context)
        context['pending_questions'] = [{'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'question': QUESTION}]
        answer = {'intent': 'answer_clarification', 'answered_question_ids': ['AMBIGUOUS_MESSAGE'],
                  'patch_operations': [{'op': 'set', 'field': 'order_id', 'value': '34', 'quote': 'ord 34'}]}
        result = validate_candidate(answer, message='ord 34', conversation=context)
        self.assertEqual(result.patch_operations[0].value, 'ORD-034')
        context['pending_questions'].append({'code': 'AMBIGUOUS_MESSAGE', 'field': 'message',
                                            'question': 'The budget and deadline need clarification.'})
        with self.assertRaises(ExtractionValidationError):
            validate_candidate(answer, message='ord 34', conversation=context)
        context['pending_questions'].pop()
        context['pending_questions'][0]['question'] = QUESTION[:-1] + ' and budget is unclear.'
        with self.assertRaises(ExtractionValidationError):
            validate_candidate(answer, message='ord 34', conversation=context)
        context['pending_questions'][0]['question'] = QUESTION
        answer['patch_operations'][0]['value'] = '35'
        with self.assertRaises(ExtractionValidationError):
            validate_candidate(answer, message='ord 34', conversation=context)

    def first_turn(self):
        model = AssignmentScript([EMPTY, {**FACTS, 'ambiguity_reason': QUESTION}])
        blocked = chat.turn(self.sid, owner='alice', request_id='first', expected_version=0,
                            db_path=self.path, message=MESSAGE, registry=model)
        self.assertEqual(model.extractions, 2)
        self.assertEqual(blocked['session']['task']['draft']['product'], 'Scarf')
        self.assertEqual(blocked['session']['task']['draft']['customer'], 'Harbor Knits')
        self.assertIn("I don't yet have the order number and quantity", blocked['assistant_message']['content'])
        self.assertNotIn('product type', blocked['assistant_message']['content'])
        self.assertIsNone(blocked['session']['task']['draft']['pieces'])
        self.assertIsNone(blocked['session']['task']['draft']['due_date'])
        return blocked

    def answer(self, version):
        # Replay the exact first follow-up extraction saved in the reported failure.
        model = SelectionScript({'intent': 'answer_clarification', 'accept_alternative': None,
            'patch_operations': [{'op': 'set', 'field': 'order_id', 'value': '34', 'quote': 'ord 34'}],
            'ambiguity_reason': None, 'unsupported_constraints': [],
            'answered_question_ids': ['AMBIGUOUS_MESSAGE']}, actions=actions(),
            intent_text=json.dumps({'task_type': 'followup'}))
        args = dict(owner='alice', request_id='answer', expected_version=version,
                    db_path=self.path, message='ord 34', registry=model)
        response = chat.turn(self.sid, **args)
        self.assertEqual(model.extractions, 1)
        self.assertEqual(response['session']['task']['draft']['order_id'], 'ORD-034')
        self.assertFalse(any(i['code'].startswith('EXTRACTION_') or i['code'] == 'AMBIGUOUS_MESSAGE'
                             for i in response['issues']))
        return response, args

    def test_reported_completed_order_is_identified_and_gets_business_validation(self):
        first = self.first_turn()
        result, args = self.answer(first['session_version'])
        self.assertTrue(any(i['code'] == 'ORDER_ALREADY_COMPLETED' for i in result['issues']))
        self.assertIn({'field': 'product', 'supplied': 'Scarf', 'recorded': 'Cardigan'},
                      result['validation_report']['resolved_differences'])
        self.assertIsNone(result['recommendation_id'])
        self.assertTrue(chat.turn(self.sid, **args)['replayed'])

    def test_matching_ready_order_uses_registered_quantity_and_produces_preview(self):
        # A separate fixture proves the recovery path when business facts permit it.
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE orders SET product='Scarf', category='ACCESSORIES', "
                               "state='UNASSIGNED', completed_pieces=0 WHERE order_id='ORD-034'")
        first = self.first_turn()
        result, args = self.answer(first['session_version'])
        self.assertEqual(result['allocation']['order_id'], 'ORD-034')
        self.assertEqual(result['allocation']['pieces'], 1000)
        self.assertIsNotNone(result['recommendation_id'])
        self.assertFalse(result['committed'])
        self.assertTrue(chat.turn(self.sid, **args)['replayed'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
