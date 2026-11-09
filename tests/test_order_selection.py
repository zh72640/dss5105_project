"""Single-order clarification and recovery with scripted models and temporary data."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage

from app.db import chat_repository
from app.db.database import Database
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate
from app.services.chat.interpretation import MULTIPLE_ORDER_IDS_QUESTION
from app.services.intake.normalization import order_ids
from tests.test_allocation_node import actions
from tests.test_architecture_alignment import NativeScript


class SelectionScript(NativeScript):
    """Script either intake route, retaining real preparation and allocation."""

    def __init__(self, candidate, **kwargs):
        super().__init__(**kwargs)
        self.candidate = candidate
        self.extractions = 0

    def invoke(self, messages):
        system = messages[0]['content'] if isinstance(messages[0], dict) else messages[0].content
        if 'Classify the current user message' in system or self.offered:
            return super().invoke(messages)
        self.extractions += 1
        return AIMessage(content=json.dumps(self.candidate))


class OrderReferenceLists(unittest.TestCase):
    def test_labeled_lists_preserve_all_references_in_source_order(self):
        for message in ('order  024, 035 and 040', 'orders 024, 035, and 040',
                        'order IDs: 024, 035 or 040', 'ORD-024, 035 and 040',
                        'order 024, ORD-035 and 040'):
            with self.subTest(message=message):
                self.assertEqual(order_ids(message, allow_short=True),
                                 ['ORD-024', 'ORD-035', 'ORD-040'])
        self.assertEqual(order_ids('order 035 and order 024, 035', allow_short=True),
                         ['ORD-035', 'ORD-024'])
        self.assertEqual(order_ids('order 024, 035 and 040'), [])

    def test_quantities_dates_and_unlabeled_numbers_are_not_list_members(self):
        for message in ('order 024, 350 pieces', 'order 024 and 2 workshops',
                        'order 024, 35 units', 'order 024, 5 days', 'order 024, 5%',
                        'order 024, 2026-04-01', 'order 024, 04/01',
                        'order 024, 35.5 pieces', 'order 024, 35-40'):
            with self.subTest(message=message):
                self.assertEqual(order_ids(message, allow_short=True), ['ORD-024'])
        self.assertEqual(order_ids('024, 035 and 040', allow_short=True), [])


    def test_product_quantities_cannot_extend_an_order_reference_list(self):
        for noun in ('vests','polo shirts','crewneck sweaters','cardigans','hoodies','scarves','beanies'):
            for quantity in ('300','1,200'):
                message=f'ORD-024, {quantity} {noun}. Needs to ship Apr 15.'
                with self.subTest(message=message):
                    self.assertEqual(order_ids(message,allow_short=True),['ORD-024'])
        self.assertEqual(order_ids('ORD-024, 035 and 300 vests',allow_short=True),['ORD-024','ORD-035'])
        self.assertEqual(order_ids('orders 024, 035 and 040, 300 vests',allow_short=True),
                         ['ORD-024','ORD-035','ORD-040'])
        self.assertEqual(order_ids('ORD-024 and ORD-300, 300 vests',allow_short=True),
                         ['ORD-024','ORD-300'])


class OrderSelectionBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'selection.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
                               as_of=date(2026, 4, 1), mode='llm')['session_id']
        with Database(self.path) as db:
            self.context = build_context(db.connection, chat_repository.snapshot(db.connection, self.sid, 'alice'))

    def turn(self, message, candidate, *, request_id, followup=False):
        model = SelectionScript(candidate, actions=actions(),
            intent_text=json.dumps({'task_type': 'followup' if followup else 'allocation'}))
        version = chat.inspect(self.sid, owner='alice', db_path=self.path)['version']
        result = chat.turn(self.sid, owner='alice', db_path=self.path, registry=model,
                           request_id=request_id, expected_version=version, message=message)
        return result, model, version

    def test_model_cannot_omit_list_or_bind_one_of_its_orders(self):
        for candidate in (
            {'intent': 'answer_clarification', 'patch_operations': []},
            {'intent': 'allocate_request', 'patch_operations': [
                {'op': 'set', 'field': 'order_id', 'value': 'ORD-024', 'quote': 'order 024'}]},
        ):
            with self.subTest(candidate=candidate):
                result = validate_candidate(candidate, message='order 024, 035 and 040',
                                            conversation=self.context)
                self.assertEqual(result.patch_operations, [])
                self.assertEqual(result.ambiguity_reason, MULTIPLE_ORDER_IDS_QUESTION)

    def test_current_unsupported_constraints_survive_order_selection(self):
        result = validate_candidate({'intent': 'allocate_request',
            'unsupported_constraints': ['unsupported_constraint']},
            message='Allocate orders 024 and 035 with a budget cap of 100.', conversation=self.context)
        self.assertEqual(result.unsupported_constraints, ['unsupported_constraint'])
        self.assertEqual(result.patch_operations, [])

    def test_reported_conversation_selects_one_order_without_repeating_requirements(self):
        first, _, _ = self.turn('Boss wants the Loom & Leaf stuff outside asap.',
            {'intent': 'allocate_request', 'patch_operations': [
                {'op': 'set', 'field': 'objective', 'value': 'min_delay', 'quote': 'asap'}]}, request_id='first')
        before = deepcopy(first['session']['task']['draft'])
        message = 'order  024, 035 and 040'
        listed, model, version = self.turn(message,
            {'intent': 'answer_clarification', 'patch_operations': []}, request_id='list', followup=True)
        self.assertEqual(listed['session']['task']['draft'], before)
        self.assertIn(MULTIPLE_ORDER_IDS_QUESTION, listed['explanation'])
        self.assertNotIn('omitted during extraction', listed['explanation'])
        self.assertIsNone(listed['recommendation_id'])
        self.assertEqual(model.extractions, 1)
        self.assertFalse(model.offered)
        replay = chat.turn(self.sid, owner='alice', db_path=self.path, registry=model,
            request_id='list', expected_version=version, message=message)
        self.assertTrue(replay['replayed'])
        self.assertEqual(model.extractions, 1)
        chosen, _, _ = self.turn('order 024', {'intent': 'answer_clarification', 'patch_operations': [
            {'op': 'set', 'field': 'order_id', 'value': 'ORD-024', 'quote': 'order 024'}]},
            request_id='choose', followup=True)
        self.assertEqual(chosen['session']['task']['draft']['order_id'], 'ORD-024')
        self.assertEqual(chosen['session']['task']['draft']['objective'], 'min_delay')
        self.assertFalse(any(i['question'] == MULTIPLE_ORDER_IDS_QUESTION
                             for i in chosen['session']['task']['issues']))
        self.assertFalse(chosen['committed'])
        trace = chat.execution_trace(self.sid, owner='alice', db_path=self.path)
        self.assertFalse(any(e['event_type'] in ('extraction_validation_failed', 'followup_validation_failed')
                             for e in trace['events']))
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_legacy_selection_question_clears_but_budget_stays_blocking(self):
        with Database(self.path) as db, db.transaction() as connection:
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['issues'] = [
                {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'severity': 'blocking',
                 'question': 'multiple_order_ids'},
                {'code': 'unsupported_constraint', 'field': 'unsupported', 'severity': 'blocking',
                 'question': 'Withdraw the existing budget cap.'}]
            chat_repository.save_task(connection, session['task'])
        result, _, _ = self.turn('order 45', {'intent': 'answer_clarification', 'patch_operations': [
            {'op': 'set', 'field': 'order_id', 'value': 'ORD-045', 'quote': 'order 45'}]}, request_id='select')
        self.assertEqual([i['code'] for i in result['session']['task']['issues']], ['unsupported_constraint'])
        self.assertIsNone(result['recommendation_id'])

    def test_short_order_answer_to_status_question_stays_read_only(self):
        sid = chat.create(owner='alice', request_id='status-session', db_path=self.path,
                           as_of=date(2026, 4, 1), mode='offline')['session_id']
        first = chat.turn(sid, owner='alice', db_path=self.path, request_id='status-question',
                          expected_version=0, message='What is the order status?')
        result = chat.turn(sid, owner='alice', db_path=self.path, request_id='status-answer',
                           expected_version=first['session_version'], message='order 45')
        self.assertEqual(result['intent'], 'query_order')
        self.assertIsNone(result['session']['task']['draft']['order_id'])
        self.assertIsNone(result['recommendation_id'])
        self.assertIn('ORD-045', result['assistant_message']['content'])

    def test_offline_list_selection_reaches_single_order_preview(self):
        sid = chat.create(owner='alice', request_id='offline', db_path=self.path,
                           as_of=date(2026, 4, 1), mode='offline')['session_id']
        result = chat.turn(sid, owner='alice', db_path=self.path, request_id='offline-list',
                           expected_version=0, message='allocate orders 045, 035 and 040')
        self.assertIsNone(result['session']['task']['draft']['order_id'])
        self.assertIn(MULTIPLE_ORDER_IDS_QUESTION, result['assistant_message']['content'])
        chosen = chat.turn(sid, owner='alice', db_path=self.path, request_id='offline-select',
                           expected_version=result['session_version'], message='order 45')
        self.assertEqual(chosen['session']['task']['draft']['order_id'], 'ORD-045')
        self.assertIsNotNone(chosen['recommendation_id'])
        self.assertFalse(chosen['committed'])

    def test_reorder_with_quantity_and_dispatch_today_reaches_preview_and_replays(self):
        message='Loom & Leaf confirmed the reorder: ORD-024, 300 vests. Needs to ship Apr 15, so it has to go out today.'
        candidate={'intent':'allocate_request','patch_operations':[
            {'op':'set','field':'order_id','value':'ORD-024','quote':'ORD-024'},
            {'op':'set','field':'customer','value':'Loom & Leaf','quote':'Loom & Leaf'},
            {'op':'set','field':'pieces','value':300,'quote':'300 vests'},
            {'op':'set','field':'product','value':'vests','quote':'vests'},
            {'op':'set','field':'due_date','value':'2026-04-15','quote':'Needs to ship Apr 15'}]}
        # Recover the task left by the old false multiple-order guard as well.
        with Database(self.path) as db,db.transaction() as c:
            task=chat_repository.snapshot(c,self.sid,'alice')['task']
            task['issues']=[{'code':'AMBIGUOUS_MESSAGE','field':'order_id','severity':'blocking',
                            'question':MULTIPLE_ORDER_IDS_QUESTION}]
            chat_repository.save_task(c,task)
        result,model,version=self.turn(message,candidate,request_id='reorder')
        self.assertEqual(result['task_state'],'RECOMMENDED')
        self.assertEqual(result['allocation']['order_id'],'ORD-024')
        self.assertEqual(result['allocation']['allocated_pieces'],300)
        self.assertEqual(result['allocation']['due_date'],'2026-04-15')
        self.assertEqual(result['session']['task']['draft']['order_date'],'2026-03-24')
        self.assertEqual(result['session']['task']['issues'],[])
        self.assertNotIn('Required information is incomplete',result['explanation'])
        self.assertFalse(result['committed'])
        replay=chat.turn(self.sid,owner='alice',db_path=self.path,registry=model,
            request_id='reorder',expected_version=version,message=message)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'],result['recommendation_id'])
        self.assertEqual(model.extractions,1)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)
