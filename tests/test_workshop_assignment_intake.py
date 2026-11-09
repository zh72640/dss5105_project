"""Assignment intake repair, preview safety and legacy recovery on disposable data."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from app.prompts import get_registry
from app.db.database import Database
from app.db import chat_repository
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate, ExtractionValidationError
from tests.test_architecture_alignment import NativeScript
from tests.test_allocation_node import actions


MESSAGE = 'OldMill is free right now — give them ORD-008.'
REFUSAL = 'This requests assigning an order directly to OldMill, but the allocation workflow does not support direct workshop assignment.'
SECOND_REFUSAL = 'This request is to assign an order to a workshop immediately, which cannot be represented as an allocation constraint.'
LEGACY_CODE = 'Assign ORD-008 to OldMill immediately based on current availability.'


def assignment(workshop='OldMill'):
    """Ground the order and hard workshop constraint in the current message."""
    return {'intent': 'allocate_request', 'patch_operations': [
        {'op': 'set', 'field': 'order_id', 'value': 'ORD-008', 'quote': 'ORD-008'},
        {'op': 'set', 'field': 'preferred_workshop', 'value': workshop, 'quote': workshop}]}


class AssignmentScript(NativeScript):
    """Return scripted extraction attempts while retaining the real graph/services."""
    def __init__(self, candidates, **kwargs):
        super().__init__(**kwargs)
        self.candidates = candidates
        self.extractions = 0
        self.prompts = []

    def invoke_task(self, mode, key, bundle):
        self.prompts.append(bundle.as_messages())
        candidate = self.candidates[min(self.extractions, len(self.candidates)-1)]
        self.extractions += 1
        return {'text': json.dumps(candidate)}, {}


class WorkshopAssignmentIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'assignment.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
            as_of=date(2026,4,1), mode='llm')['session_id']
        with Database(self.path) as db:
            session = chat_repository.snapshot(db.connection, self.sid, 'alice')
            self.context = build_context(db.connection, session)

    def turn(self, model, text=MESSAGE):
        return chat.turn(self.sid, owner='alice', request_id='assign', expected_version=0,
                         db_path=self.path, message=text, registry=model)

    def validation(self):
        return [e['detail'] for e in chat.execution_trace(self.sid, owner='alice', db_path=self.path)['events']
                if e['event_type'] == 'extraction_validation_failed']

    def test_missing_order_triggers_repair_then_reaches_actual_suspended_workshop(self):
        bad = {'intent':'unsupported_or_ambiguous', 'patch_operations':[], 'ambiguity_reason':REFUSAL}
        model = AssignmentScript([bad, assignment()])
        result = self.turn(model)
        self.assertEqual(model.extractions, 2)
        self.assertEqual(self.validation()[0]['reason'], 'OMITTED_EXPLICIT_ORDER_ID')
        self.assertEqual(self.validation()[0]['expected_fields'], {'order_id':'ORD-008','preferred_workshop':'W7'})
        self.assertEqual(self.validation()[0]['missing_fields'], ['order_id','preferred_workshop'])
        self.assertEqual(result['session']['task']['draft']['order_id'], 'ORD-008')
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'], 'W7')
        self.assertEqual(result['validation_report']['resolved_fields']['pieces'], 600)
        self.assertTrue(any(i['code'] == 'PREFERRED_INELIGIBLE' for i in result['issues']))
        self.assertIn('is currently suspended', result['explanation'])
        self.assertNotIn('Required information is incomplete', result['explanation'])
        self.assertNotIn('does not support direct workshop assignment', result['explanation'])
        self.assertFalse(model.offered)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT status FROM workshops WHERE workshop_id='W7'").fetchone()[0], 'SUSPENDED')
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)
        replay = self.turn(model)
        self.assertTrue(replay['replayed'])
        self.assertEqual(model.extractions, 2)

    def test_outsourcing_example_reaches_preview_and_replays_without_production_writes(self):
        """Run the active prompt example through real intake and planning with a mock model."""
        prompt = get_registry().get('allocation.extract')
        example = next(e for e in prompt.examples if 'this one goes outside' in e.user)
        model = AssignmentScript([json.loads(example.assistant)], actions=actions())
        result = self.turn(model, example.user)
        self.assertEqual(result['session']['task']['draft']['order_id'], 'ORD-017')
        self.assertEqual(result['validation_report']['resolved_fields']['pieces'], 800)
        self.assertIsNotNone(result['recommendation_id'])
        self.assertFalse(result['committed'])
        self.assertFalse(result['session']['task']['issues'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)
        self.assertTrue(self.turn(model, example.user)['replayed'])
        self.assertEqual(model.extractions, 1)

    def test_outsourcing_context_does_not_remove_an_actual_unsupported_budget(self):
        """Background context cannot authorize dropping a separate unsupported requirement."""
        prompt = get_registry().get('allocation.extract')
        example = next(e for e in prompt.examples if 'this one goes outside' in e.user)
        candidate = json.loads(example.assistant)
        candidate['unsupported_constraints'] = ['unsupported_constraint']
        result = self.turn(AssignmentScript([candidate]), example.user + ' Keep total cost under 100.')
        self.assertTrue(any(i['code'] == 'unsupported_constraint' for i in result['issues']))
        self.assertIsNone(result['recommendation_id'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_arbitrary_unsupported_prose_is_repaired_not_persisted_as_an_issue_code(self):
        bad = {'intent':'unsupported_or_ambiguous', 'patch_operations':[],
               'ambiguity_reason':SECOND_REFUSAL, 'unsupported_constraints':[LEGACY_CODE]}
        model = AssignmentScript([bad, assignment()])
        result = self.turn(model)
        self.assertEqual(model.extractions, 2)
        self.assertEqual(self.validation()[0]['stage'], 'format')
        self.assertTrue(any(e['location'] == ['unsupported_constraints',0] for e in self.validation()[0]['errors']))
        self.assertFalse(any(i['code'] == LEGACY_CODE for i in result['issues']))
        self.assertIn('is currently suspended', result['explanation'])

    def test_missing_workshop_is_repaired_before_planning(self):
        incomplete = assignment()
        incomplete['patch_operations'].pop()
        model = AssignmentScript([incomplete, assignment()])
        result = self.turn(model)
        self.assertEqual(self.validation()[0]['reason'], 'OMITTED_REQUIRED_WORKSHOP')
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'], 'W7')

    def test_supported_assignment_cannot_be_relabeled_as_an_unsupported_capability(self):
        for constraint in ([], ['unsupported_constraint']):
            candidate = {**assignment(), 'intent':'unsupported_or_ambiguous',
                         'ambiguity_reason':REFUSAL, 'unsupported_constraints':constraint}
            with self.subTest(constraint=constraint), self.assertRaises(ExtractionValidationError) as failed:
                validate_candidate(candidate, message=MESSAGE, conversation=self.context)
            self.assertEqual(failed.exception.detail['reason'], 'MISCLASSIFIED_WORKSHOP_ASSIGNMENT')

    def test_two_failed_attempts_preserve_the_existing_task_without_business_writes(self):
        bad = {'intent':'unsupported_or_ambiguous', 'patch_operations':[], 'ambiguity_reason':REFUSAL}
        model = AssignmentScript([bad])
        result = self.turn(model)
        self.assertEqual(model.extractions, 2)
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_EVIDENCE_INVALID')
        self.assertEqual(result['session']['task']['task_version'], 0)
        self.assertIsNone(result['session']['task']['draft']['order_id'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0], 0)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_eligible_required_workshop_produces_a_preview_not_a_commit(self):
        model = AssignmentScript([assignment('Nimble Needle')], actions=actions())
        result = self.turn(model, 'Nimble Needle is free right now — give them ORD-008.')
        self.assertEqual(result['allocation']['order_id'], 'ORD-008')
        self.assertEqual(result['allocation']['workshop_id'], 'W6')
        self.assertFalse(result['committed'])
        self.assertIsNotNone(result['recommendation_id'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_already_bound_order_and_workshop_can_be_omitted_on_a_revision(self):
        context = deepcopy(self.context)
        context['draft'].update(order_id='ORD-008', preferred_workshop='W7')
        result = validate_candidate({'intent':'modify_constraints', 'patch_operations':[]},
                                    message=MESSAGE, conversation=context)
        self.assertEqual(result.patch_operations, [])

    def test_multiple_orders_and_hypotheticals_do_not_force_one_order_or_workshop(self):
        candidate = {'intent':'unsupported_or_ambiguous', 'patch_operations':[],
                     'ambiguity_reason':'Specify one order.'}
        validate_candidate(candidate, message='Assign ORD-008 or ORD-009 to OldMill.', conversation=self.context)
        validate_candidate(candidate, message='What if we gave ORD-008 to OldMill?', conversation=self.context)
        validate_candidate(candidate, message="Do not give OldMill ORD-008.", conversation=self.context)

    def test_real_unsupported_requirements_remain_blockers(self):
        candidate = {**assignment(), 'unsupported_constraints':['unsupported_constraint']}
        checked = validate_candidate(candidate, message=MESSAGE+' Keep total cost under 100.', conversation=self.context)
        self.assertEqual(checked.unsupported_constraints, ['unsupported_constraint'])

    def test_other_blockers_do_not_permit_dropping_the_required_workshop(self):
        candidate = assignment()
        candidate['patch_operations'].pop()
        candidate['unsupported_constraints'] = ['unsupported_constraint']
        with self.assertRaises(ExtractionValidationError) as failed:
            validate_candidate(candidate, message=MESSAGE+' Keep total cost under 100.', conversation=self.context)
        self.assertEqual(failed.exception.detail['reason'], 'OMITTED_REQUIRED_WORKSHOP')

    def test_old_refusal_does_not_block_a_new_eligible_workshop_preview(self):
        with Database(self.path) as db, db.transaction() as connection:
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['state'] = 'BLOCKED'
            session['task']['issues'] = [
                {'code':'AMBIGUOUS_MESSAGE','field':'message','severity':'blocking','question':REFUSAL},
                {'code':LEGACY_CODE,'field':'unsupported','severity':'blocking','question':'Legacy refusal.'}]
            chat_repository.save_task(connection,session['task'])
        result = self.turn(AssignmentScript([assignment('Nimble Needle')], actions=actions()),
                           'Give ORD-008 to Nimble Needle.')
        self.assertEqual(result['allocation']['workshop_id'], 'W6')
        self.assertEqual(result['session']['task']['issues'], [])
        self.assertFalse(result['committed'])

    def test_renamed_workshop_alias_is_taken_from_current_database_context(self):
        context = deepcopy(self.context)
        context['workshop_names']['W6'] = 'Busy Bee'
        checked = validate_candidate(assignment('Busy Bee'), message='Give ORD-008 to Busy Bee.', conversation=context)
        self.assertEqual(checked.patch_operations[1].value, 'W6')

    def test_old_assignment_refusals_are_recoverable_while_budget_blockers_remain(self):
        with Database(self.path) as db, db.transaction() as connection:
            session = chat_repository.snapshot(connection, self.sid, 'alice')
            session['task']['state'] = 'BLOCKED'
            session['task']['issues'] = [
                {'code':'AMBIGUOUS_MESSAGE','field':'message','severity':'blocking','question':REFUSAL},
                {'code':'AMBIGUOUS_MESSAGE','field':'message','severity':'blocking','question':SECOND_REFUSAL},
                {'code':LEGACY_CODE,'field':'unsupported','severity':'blocking','question':'Legacy direct assignment rejection.'},
                {'code':'unsupported_constraint','field':'unsupported','severity':'blocking','question':'The existing budget must be resolved.'}]
            chat_repository.save_task(connection,session['task'])
        result = self.turn(AssignmentScript([assignment()]))
        issues = result['session']['task']['issues']
        self.assertEqual([i['code'] for i in issues], ['unsupported_constraint'])
        self.assertIsNone(result['recommendation_id'])
        self.assertIn('existing budget', result['explanation'])
