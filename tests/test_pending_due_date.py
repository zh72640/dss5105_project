"""Undated previews use scripted models and isolated, temporary business databases."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage

from app.allocator import AllocationRequest, allocate
from app.db.database import Database
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate
from app.services.chat.explanation_guard import claim_problem
from app.services.intake.evidence import requests_recommendation
from tests.test_allocation_node import actions
from tests.test_architecture_alignment import NativeScript


MESSAGE = 'ORD-066 due date just moved up — will confirm the new date after the call, but line something up.'


class PendingScript(NativeScript):
    """Return a pending marker initially and an evidenced replacement date later."""
    def invoke_task(self, mode, key, bundle):
        message = bundle.as_messages()[-1]['content']
        if 'Apr 15' in message:
            candidate = {'intent': 'modify_constraints', 'patch_operations': [
                {'op': 'set', 'field': 'due_date', 'value': '2026-04-15', 'quote': 'Apr 15'}]}
        elif 'ORD-066' in message:
            candidate = {'intent': 'allocate_request', 'patch_operations': [
                {'op': 'set', 'field': 'order_id', 'value': 'ORD-066', 'quote': 'ORD-066'}],
                'ambiguity_reason': 'unconfirmed_due_date,unconfirmed_due_date'}
        else:
            candidate = {'intent': 'modify_constraints', 'patch_operations': []}
        return {'text': json.dumps(candidate)}, {}


class PendingDueDateBehavior(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / 'pending.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
            as_of=date(2026, 4, 1), mode='llm')['session_id']

    def turn(self, model, message=MESSAGE, request_id='preview', version=0):
        return chat.turn(self.sid, owner='alice', request_id=request_id,
                         expected_version=version, db_path=self.path, message=message, registry=model)

    def test_explicit_request_returns_undated_preview_and_replays_without_writes(self):
        model = PendingScript(actions=actions())
        with Database(self.path) as db:
            old = dict(db.connection.execute("SELECT * FROM orders WHERE order_id='ORD-066'").fetchone())
        response = self.turn(model)
        self.assertEqual(response['task_state'], 'RECOMMENDED')
        self.assertFalse(response['committed'])
        payload = response['allocation']
        self.assertIsNone(payload['due_date'])
        self.assertIsNone(payload['delay_days'])
        saved = response['session']['recommendation']['result']
        self.assertIsNone(saved['deadline_met'])
        self.assertIn('DUE_DATE_UNCONFIRMED', saved['warnings'])
        self.assertTrue(all(p['deadline_met'] is None for p in saved['candidate_plans']))
        self.assertIn('No confirmed due date', response['explanation'])
        self.assertNotIn('unconfirmed_due_date', response['explanation'])
        replay = self.turn(model)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'], response['recommendation_id'])
        with Database(self.path) as db:
            self.assertEqual(dict(db.connection.execute("SELECT * FROM orders WHERE order_id='ORD-066'").fetchone()), old)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0], 1)

    def test_offline_mode_can_proceed_after_a_pending_date_notice(self):
        sid = chat.create(owner='alice', request_id='offline', db_path=self.path,
                          as_of=date(2026,4,1), mode='offline')['session_id']
        blocked = chat.turn(sid, owner='alice', request_id='offline-pending', expected_version=0,
            db_path=self.path, message='ORD-066 due date moved; will confirm later.')
        self.assertIsNone(blocked['recommendation_id'])
        ready = chat.turn(sid, owner='alice', request_id='offline-proceed',
            expected_version=blocked['session_version'], db_path=self.path, message='Line something up anyway.')
        self.assertIsNotNone(ready['recommendation_id'])
        self.assertIsNone(ready['session']['recommendation']['result']['due_date'])
        self.assertIn('No confirmed due date', ready['assistant_message']['content'])

    def test_pending_information_without_instruction_asks_once_then_can_proceed(self):
        model = PendingScript(actions=actions())
        blocked = self.turn(model, 'ORD-066 due date moved; will confirm the new date after the call.')
        self.assertIsNone(blocked['recommendation_id'])
        self.assertFalse(model.offered)
        text = blocked['assistant_message']['content']
        self.assertNotIn('unconfirmed_due_date', text)
        self.assertEqual(text.count('The new due date is unconfirmed.'), 1)
        ready = self.turn(model, 'Line something up anyway.', 'proceed', blocked['session_version'])
        self.assertIsNotNone(ready['recommendation_id'])
        self.assertIsNone(ready['allocation']['due_date'])

    def test_follow_up_replaces_pending_date_and_invalidates_old_preview(self):
        first = self.turn(PendingScript(actions=actions()))
        model = PendingScript(actions=actions(), intent_text='{"task_type":"compat"}')
        revised = self.turn(model, 'Apr 15', 'date', first['session_version'])
        self.assertNotEqual(first['recommendation_id'], revised['recommendation_id'])
        self.assertEqual(revised['allocation']['due_date'], '2026-04-15')
        self.assertIsInstance(revised['allocation']['delay_days'], int)
        self.assertNotIn('DUE_DATE_UNCONFIRMED', revised['allocation']['warnings'])
        self.assertNotIn('No confirmed due date', revised['explanation'])
        with Database(self.path) as db:
            old = db.connection.execute('SELECT status FROM chat_recommendations WHERE recommendation_id=?',
                                        (first['recommendation_id'],)).fetchone()[0]
            self.assertEqual(old, 'superseded')
            self.assertNotEqual(db.connection.execute("SELECT due_date FROM orders WHERE order_id='ORD-066'").fetchone()[0], '2026-04-15')
        with self.assertRaises(chat.ChatError):
            chat.turn(self.sid, owner='alice', request_id='old-confirm', expected_version=revised['session_version'],
                db_path=self.path, action='confirm', recommendation_id=first['recommendation_id'])

    def test_confirmation_and_replay_use_the_existing_submission_rules(self):
        preview = self.turn(PendingScript(actions=actions()))
        kwargs = dict(owner='alice', request_id='confirm', expected_version=preview['session_version'],
                      db_path=self.path, action='confirm', recommendation_id=preview['recommendation_id'])
        confirmed = chat.turn(self.sid, **kwargs)
        self.assertTrue(confirmed['committed'])
        self.assertIn('No confirmed due date', confirmed['assistant_message']['content'])
        self.assertTrue(chat.turn(self.sid, **kwargs)['replayed'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 1)

    def test_changed_business_facts_require_review_before_commit(self):
        preview = self.turn(PendingScript(actions=actions()))
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE orders SET pieces=pieces+1 WHERE order_id='ORD-066'")
        changed = chat.turn(self.sid, owner='alice', request_id='changed-confirm',
            expected_version=preview['session_version'], db_path=self.path, action='confirm',
            recommendation_id=preview['recommendation_id'])
        self.assertFalse(changed['committed'])
        self.assertEqual(changed['http_status'], 409)

    def test_explicit_proceed_does_not_discard_unrelated_ambiguity(self):
        with Database(self.path) as db:
            context = build_context(db.connection, chat.inspect(self.sid, owner='alice', db_path=self.path))
        parsed = validate_candidate({'intent': 'allocate_request',
            'patch_operations': [{'op':'set','field':'order_id','value':'ORD-066','quote':'ORD-066'}],
            'ambiguity_reason': 'unconfirmed_due_date,multiple_order_ids'}, message=MESSAGE, conversation=context)
        self.assertTrue(parsed.recommend_without_due_date)
        self.assertEqual(parsed.ambiguity_reason, 'multiple_order_ids')

    def test_legacy_duplicate_pending_issues_can_resume(self):
        model = PendingScript(actions=actions())
        response = self.turn(model, 'ORD-066 due date moved; will confirm later.')
        with Database(self.path) as db, db.transaction() as connection:
            from app.db import chat_repository
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            task = session['task']
            task['sources'].pop('due_date', None)
            task['issues'] = [{'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'severity': 'blocking',
                               'question': 'unconfirmed_due_date,unconfirmed_due_date'}]
            chat_repository.save_task(connection, task)
        resumed = self.turn(model, 'Line something up.', 'resume', response['session_version'])
        self.assertIsNotNone(resumed['recommendation_id'])
        self.assertIsNone(resumed['allocation']['due_date'])

    def test_repairing_an_invented_date_can_still_honor_explicit_planning(self):
        from app.services.chat.extraction import salvage_due_date, ExtractionValidationError
        with Database(self.path) as db:
            context = build_context(db.connection, chat.inspect(self.sid, owner='alice', db_path=self.path))
        candidate = {'intent': 'allocate_request', 'ambiguity_reason': 'unconfirmed_due_date',
            'patch_operations': [
                {'op': 'set', 'field': 'order_id', 'value': 'ORD-066', 'quote': 'ORD-066'},
                {'op': 'set', 'field': 'due_date', 'value': '2026-04-20', 'quote': 'new date'}]}
        with self.assertRaises(ExtractionValidationError) as invalid:
            validate_candidate(candidate, message=MESSAGE, conversation=context)
        repaired = salvage_due_date(candidate, invalid.exception, message=MESSAGE, conversation=context)
        self.assertTrue(repaired.recommend_without_due_date)
        self.assertIsNone(repaired.ambiguity_reason)
        self.assertEqual([p.field for p in repaired.patch_operations], ['order_id'])

    def test_other_explicitly_unconfirmed_date_phrases_do_not_reuse_old_dates(self):
        from app.services.intake.evidence import pending_due_date
        for text in ('The due date is TBD; recommend a workshop.',
                     'No confirmed due date yet; line something up.',
                     'The ship date is not yet confirmed; please proceed.'):
            with self.subTest(text=text):
                self.assertTrue(pending_due_date(text))
        self.assertFalse(pending_due_date('The due date is confirmed for Apr 15.'))

    def test_negation_and_hypotheticals_do_not_authorize_date_free_planning(self):
        for text in ("Do not allocate yet.", "Don't line something up.", 'What if we recommend a workshop?', 'Wait to dispatch.', 'We should not recommend anything yet.', "We won't allocate yet."):
            with self.subTest(text=text):
                self.assertFalse(requests_recommendation(text))
        for text in ('Allocate it.', 'Recommend a workshop.', 'Find a suitable workshop.', 'Please proceed.', 'Line something up.', 'The date is not confirmed but recommend a workshop.'):
            self.assertTrue(requests_recommendation(text))

    def test_undated_explanation_rejects_on_time_claims(self):
        preview = self.turn(PendingScript(actions=actions()))
        self.assertEqual(claim_problem('This plan meets the deadline.', preview['allocation']), 'unconfirmed_deadline_claim')

    def test_hard_deadline_is_not_silently_relaxed(self):
        from app.services.chat import operations
        preview = self.turn(PendingScript(actions=actions()))
        with Database(self.path) as db, db.transaction() as connection:
            from app.db import chat_repository
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['draft']['deadline_required'] = True
            report = operations.check_requirements(connection, session, date(2026,4,1))['report']
        self.assertFalse(report['ready_for_planning'])
        self.assertTrue(any(i['code'] == 'DUE_DATE_REQUIRED_FOR_DEADLINE' for i in report['blocking_issues']))

    def test_weighted_scoring_uses_completion_evidence_without_fabricated_lateness(self):
        from app.db.workshop_repository import get_all
        with Database(self.path) as db:
            workshops = get_all(db.connection, date(2026,4,1))
        order = {'pieces':100, 'category':'TOPS', 'due_date':None}
        result = allocate(AllocationRequest(order=order, workshops=workshops, as_of=date(2026,4,1), objective='weighted_hybrid'))
        self.assertTrue(result['success'])
        self.assertIsNone(result['deadline_met'])
        evidence = result['explanation_evidence']
        self.assertIn('completion', evidence['method'])
        self.assertNotIn('lateness', json.dumps(evidence))
        dated = allocate(AllocationRequest(order={**order, 'due_date':'2026-04-20'}, workshops=workshops,
                                          as_of=date(2026,4,1), objective='weighted_hybrid'))
        self.assertEqual(result['recommended_workshop_id'], dated['recommended_workshop_id'])
        with self.assertRaises(ValueError):
            allocate(AllocationRequest(order=order, workshops=workshops, as_of=date(2026,4,1),
                                       objective='min_delay', deadline_required=True))
