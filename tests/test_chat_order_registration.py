"""Conversational order entry using isolated SQLite and scripted model responses."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config.settings import Settings
from app.db.database import Database
from app.db.order_repository import get_order
from app.main import create_app
from app.schemas.order_intake import ORDER_FIELDS
from app.services.chat import service as chat, order_registration as registration
from app.services import order_intake
from tests.test_architecture_alignment import NativeScript

FACTS = dict(order_id='ORD-901', customer='ABC', product='Vest', category='TOPS', pieces=300,
             order_date='2026-11-11', due_date='2026-11-25')
MESSAGE = 'Add order ORD-901; customer: ABC; product: Vest; category: TOPS; pieces: 300; ordered 2026-11-11; due 2026-11-25.'


class RegistrationModel(NativeScript):
    def __init__(self, outputs):
        super().__init__(intent_text='{"task_type":"order_registration"}')
        self.outputs = list(outputs)
        self.registration_calls = 0

    def invoke(self, messages):
        system = messages[0]['content'] if isinstance(messages[0], dict) else messages[0].content
        if 'Extract order registration details' in system:
            self.registration_calls += 1
            value = self.outputs.pop(0)
            if isinstance(value, Exception):
                raise value
            return AIMessage(content=json.dumps(value))
        return super().invoke(messages)


def extraction(facts=FACTS, message=MESSAGE):
    return {'patches': [{'field': key, 'value': value, 'quote': message} for key, value in facts.items()]}


class ChatRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'chat.sqlite3')
        self.sid = chat.create(owner='alice', request_id='new', db_path=self.path, as_of=date(2026, 4, 1), mode='offline')['session_id']

    def inspect(self):
        return chat.inspect(self.sid, owner='alice', db_path=self.path)

    def send(self, message, **kwargs):
        return chat.turn(self.sid, owner='alice', request_id=str(uuid4()), expected_version=self.inspect()['version'],
                         db_path=self.path, message=message, **kwargs)

    def decision(self, action='create', review=None, **kwargs):
        review = review or self.inspect()['order_registration']['review']
        return dict(review_id=review['review_id'], action=action, expected_version=review['expected_version'],
            reason='Checked against customer instructions.', confirmed_order_id=review['order_id'],
            verified_fields=[item['field'] for item in review['differences']], **kwargs)

    def decide(self, action='create', **kwargs):
        return self.send('', action='order_decision', order_decision=self.decision(action), **kwargs)

    def order(self, oid='ORD-901'):
        with Database(self.path) as db:
            return get_order(db.connection, oid)

    def use_llm(self):
        self.sid = chat.create(owner='alice', request_id='llm-new', db_path=self.path,
                              as_of=date(2026, 4, 1), mode='llm')['session_id']

    def test_one_sentence_prepares_but_never_creates_until_explicit_decision(self):
        response = self.send(MESSAGE)
        task = response['session']['order_registration']
        self.assertEqual(task['draft'], FACTS)
        self.assertEqual(task['status'], 'REVIEW')
        self.assertIsNone(self.order())
        self.assertFalse(response['committed'])
        self.send('yes, confirm it')
        self.assertIsNone(self.order())
        self.assertEqual(self.inspect()['order_registration']['review_id'], task['review_id'])
        result = self.decide()
        self.assertEqual(self.order()['pieces'], 300)
        self.assertEqual(result['session']['order_registration']['status'], 'COMPLETED')
        self.assertIn('registered', result['assistant_message']['content'])
        self.assertFalse(result['committed'])  # allocation commit has a separate meaning

    def test_blank_followup_does_not_change_registration(self):
        self.send(MESSAGE)
        before = self.inspect()
        with self.assertRaises(chat.ChatError) as raised:
            self.send('   ')
        self.assertEqual(raised.exception.code, 'INVALID_MESSAGE')
        self.assertEqual(self.inspect(), before)

    def test_v10_migration_preserves_existing_chat_and_manual_review(self):
        old_path = str(Path(self.temp.name) / 'v10.sqlite3')
        with patch.object(Database, '_upgrade_chat_registration'), patch('app.db.chat_registration_repository.get', return_value=None):
            session = chat.create(owner='alice', request_id='old-chat', db_path=old_path, mode='offline', as_of=date(2026, 11, 11))
            review = order_intake.check({'request_id':'old-review', 'order':FACTS}, actor='alice', db_path=old_path)
            with Database(old_path) as db:
                self.assertEqual(db.connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 10)
                count = db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        restored = chat.inspect(session['session_id'], owner='alice', db_path=old_path)
        self.assertIsNone(restored['order_registration'])
        self.assertEqual(order_intake.get_review(review['review_id'], actor='alice', db_path=old_path), review)
        with Database(old_path) as db:
            self.assertEqual(db.connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 11)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0], count)

    def test_multiturn_missing_fields_survive_restart(self):
        first = self.send('Add order ORD-901 for ABC; 300 vests; TOPS.')
        self.assertIn('order date', first['assistant_message']['content'])
        self.assertIsNone(self.inspect()['order_registration']['review'])
        second = self.send('ordered 2026-11-11; due 2026-11-25.')
        self.assertEqual(second['session']['order_registration']['draft'], FACTS)
        self.assertEqual(self.inspect()['order_registration']['status'], 'REVIEW')
        self.assertIsNone(self.order())

    def test_same_order_does_not_create_duplicate_or_touch_version(self):
        self.send(MESSAGE); self.decide()
        before = self.order()
        result = self.send(MESSAGE)
        self.assertEqual(result['session']['order_registration']['review']['match'], 'identical')
        self.assertEqual(self.order(), before)

    def test_mismatch_rejection_and_verified_approval_share_manual_audit(self):
        self.send(MESSAGE); self.decide()
        self.send(MESSAGE.replace('pieces: 300', 'pieces: 350'))
        rejected = self.decide('reject')
        self.assertEqual(self.order()['pieces'], 300)
        self.assertEqual(rejected['session']['order_registration']['review']['decision']['outcome'], 'REJECTED')
        self.send(MESSAGE.replace('pieces: 300', 'pieces: 350'))
        result = self.decide('update')
        self.assertEqual(self.order()['pieces'], 350)
        self.assertEqual(self.order()['version'], 1)
        self.assertEqual(result['session']['order_registration']['review']['decision']['outcome'], 'UPDATED')
        history = order_intake.history(actor='alice', db_path=self.path, order_id='ORD-901')
        self.assertEqual({r['decision']['outcome'] for r in history['items']}, {'CREATED', 'REJECTED', 'UPDATED'})

    def test_secondary_verification_is_enforced_through_chat(self):
        self.send(MESSAGE); self.decide()
        self.send(MESSAGE.replace('pieces: 300', 'pieces: 350'))
        body = self.decision('update'); body['verified_fields'] = []
        result = self.send('', action='order_decision', order_decision=body)
        self.assertEqual(result['http_status'], 409)
        self.assertIn('Verify every changed field', result['assistant_message']['content'])
        self.assertEqual(self.order()['pieces'], 300)

    def test_revision_withdraws_old_review_and_new_card_has_current_values(self):
        self.send(MESSAGE)
        old = self.decision()
        self.send('pieces: 400')
        task = self.inspect()['order_registration']
        self.assertNotEqual(task['review_id'], old['review_id'])
        self.assertEqual(task['review']['proposed']['pieces'], 400)
        with self.assertRaises(chat.ChatError):
            self.send('', action='order_decision', order_decision=old)
        self.assertEqual(order_intake.get_review(old['review_id'], actor='alice', db_path=self.path)['decision']['outcome'], 'REJECTED')

    def test_invalid_revision_withdraws_pending_card_without_losing_valid_draft(self):
        self.send(MESSAGE)
        old = self.decision()
        result = self.send('due 2026-02-30')
        task = result['session']['order_registration']
        self.assertIsNone(task['review'])
        self.assertEqual(task['draft'], FACTS)
        self.assertTrue(task['issues'])
        with self.assertRaises(chat.ChatError):
            self.send('', action='order_decision', order_decision=old)

    def test_creation_conflict_is_recorded_and_not_mislabeled_cancelled(self):
        self.send(MESSAGE)
        review = order_intake.check({'request_id':'other-check', 'order': FACTS}, actor='bob', db_path=self.path)
        order_intake.decide(review['review_id'], {'request_id':'other-create','action':'create','expected_version':None,
            'reason':'A second operator registered it.'}, actor='bob', db_path=self.path)
        result = self.decide()
        self.assertEqual(result['http_status'], 409)
        self.assertIn('changed after this check', result['assistant_message']['content'])
        self.assertEqual(result['session']['order_registration']['review']['decision']['outcome'], 'ORDER_CHANGED')

    def test_decline_in_conversation_and_archiving_record_rejection(self):
        self.send(MESSAGE)
        result = self.send('No, keep existing values')
        self.assertEqual(result['session']['order_registration']['review']['decision']['outcome'], 'REJECTED')
        self.assertIsNone(self.order())
        self.send(MESSAGE)
        rid = self.inspect()['order_registration']['review_id']
        self.send('', action='archive')
        self.assertEqual(order_intake.get_review(rid, actor='alice', db_path=self.path)['decision']['outcome'], 'REJECTED')

    def test_decision_replay_is_stable_and_payload_reuse_conflicts(self):
        self.send(MESSAGE)
        kwargs = dict(owner='alice', request_id='decision', expected_version=self.inspect()['version'], db_path=self.path,
                      action='order_decision', order_decision=self.decision())
        first = chat.turn(self.sid, **kwargs)
        replayed = chat.turn(self.sid, **kwargs)
        self.assertEqual(replayed, {**first, 'replayed': True})
        kwargs['order_decision'] = {**kwargs['order_decision'], 'reason':'Different'}
        with self.assertRaises(chat.ChatError):
            chat.turn(self.sid, **kwargs)
        self.assertEqual(self.order()['version'], 0)

    def test_owner_other_session_and_stale_version_cannot_confirm(self):
        self.send(MESSAGE)
        decision = self.decision()
        with self.assertRaises(chat.ChatError):
            chat.turn(self.sid, owner='bob', request_id='forged', expected_version=1, db_path=self.path,
                      action='order_decision', order_decision=decision)
        other = chat.create(owner='alice', request_id='other-session', db_path=self.path, as_of=date(2026,4,1))['session_id']
        with self.assertRaises(chat.ChatError):
            chat.turn(other, owner='alice', request_id='wrong-session', expected_version=0, db_path=self.path,
                      action='order_decision', order_decision=decision)
        self.send('Please show the review again')
        with self.assertRaises(chat.ChatError):
            chat.turn(self.sid, owner='alice', request_id='stale', expected_version=1, db_path=self.path,
                      action='order_decision', order_decision=decision)
        self.assertIsNone(self.order())

    def test_order_and_audit_roll_back_if_chat_message_write_fails(self):
        self.send(MESSAGE)
        version = self.inspect()['version']
        with patch('app.db.chat_repository.insert_message', side_effect=sqlite3.OperationalError('message unavailable')):
            with self.assertRaises(sqlite3.OperationalError):
                self.decide()
        self.assertIsNone(self.order())
        self.assertIsNone(self.inspect()['order_registration']['review']['decision'])
        self.assertEqual(self.inspect()['version'], version)

    def test_registration_invalidates_existing_allocation_preview(self):
        preview = self.send('Allocate ORD-045.')
        recommendation = preview['recommendation_id']
        self.send(MESSAGE)
        self.assertEqual(self.inspect()['recommendation']['status'], 'superseded')
        with self.assertRaises(chat.ChatError):
            self.send('', action='confirm', recommendation_id=recommendation)
        self.assertEqual(self.order('ORD-045')['state'], 'READY')

    def test_newly_registered_order_can_be_allocated_separately(self):
        self.send(MESSAGE); self.decide()
        preview = self.send('Allocate ORD-901.')
        self.assertEqual(preview['session']['recommendation']['status'], 'valid')
        self.assertFalse(preview['committed'])

    def test_llm_routing_uses_fixed_registration_node_without_allocation_tools(self):
        self.use_llm()
        model = RegistrationModel([extraction()])
        response = self.send(MESSAGE, registry=model)
        self.assertEqual(response['intent'], 'order_registration')
        self.assertEqual(response['session']['order_registration']['review']['match'], 'missing')
        self.assertEqual(model.offered, [])
        self.assertIsNone(self.order())
        self.decide()
        self.assertEqual(self.order()['pieces'], 300)

    def test_llm_short_followup_continues_saved_registration_task(self):
        self.use_llm()
        first = 'Add order ORD-901; customer: ABC; 300 vests; TOPS.'
        partial = {k:v for k,v in FACTS.items() if not k.endswith('date')}
        self.send(first, registry=RegistrationModel([extraction(partial, first)]))
        followup = 'ordered 2026-11-11; due 2026-11-25'
        model = RegistrationModel([extraction({k:v for k,v in FACTS.items() if k.endswith('date')}, followup)])
        # Active registration skips generic intent classification and goes to its own node.
        response = self.send(followup, registry=model)
        self.assertEqual(response['session']['order_registration']['draft'], FACTS)
        self.assertEqual(model.registration_calls, 1)

    def test_ungrounded_llm_values_and_success_claims_never_write_orders(self):
        self.use_llm()
        bad = extraction({**FACTS, 'customer':'Invented client'})
        model = RegistrationModel([bad, bad])
        response = self.send(MESSAGE, registry=model)
        self.assertEqual(model.registration_calls, 2)
        self.assertIsNone(response['session']['order_registration']['review'])
        self.assertIsNone(self.order())
        self.assertNotIn('Invented client', response['assistant_message']['content'])
        claim = {'ambiguity':'Order was created successfully. You can trust me.'}
        response = self.send('Continue', registry=RegistrationModel([claim]))
        self.assertNotIn('created successfully', response['assistant_message']['content'])

    def test_llm_retry_after_finalization_failure_reuses_saved_review(self):
        self.use_llm()
        model = RegistrationModel([extraction()])
        kwargs = dict(owner='alice', request_id='retry-me', expected_version=0, db_path=self.path, message=MESSAGE, registry=model)
        with patch('app.db.agent_repository.finalize_turn', side_effect=sqlite3.OperationalError('interrupted')):
            with self.assertRaises(sqlite3.OperationalError):
                chat.turn(self.sid, **kwargs)
        rid = self.inspect()['order_registration']['review_id']
        response = chat.turn(self.sid, **kwargs)
        self.assertEqual(response['session']['order_registration']['review_id'], rid)
        self.assertEqual(model.registration_calls, 1)
        self.assertEqual(order_intake.history(actor='alice', db_path=self.path)['total'], 1)

    def test_http_contract_exposes_registration_and_does_not_accept_forged_actor(self):
        client = self.enterContext(TestClient(create_app(Settings(db_path=self.path, require_auth=False))))
        response = client.post('/api/chat/sessions', json={'request_id':'http-new', 'mode':'offline', 'message':MESSAGE})
        self.assertEqual(response.status_code, 200)
        data = response.json(); review = data['session']['order_registration']['review']
        body = dict(request_id='http-decision', expected_version=data['session_version'], action='order_decision',
                    order_decision=self.decision(review=review))
        url = f"/api/chat/sessions/{data['session_id']}/turns"
        self.assertEqual(client.post(url, json={**body, 'actor':'forged'}).status_code, 400)
        self.assertEqual(client.post(url, json=body).status_code, 200)
        self.assertEqual(self.order()['pieces'], 300)


if __name__ == '__main__':
    unittest.main()
