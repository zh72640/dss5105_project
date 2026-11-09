"""Candidate-workshop questions use prepared allocation checks on temporary data."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage

from app.db.database import Database
from app.db import chat_repository
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate
from tests.test_allocation_node import actions
from tests.test_architecture_alignment import NativeScript


QUESTION = 'QuickStitch for the scarves on ORD-103?'


def candidate(workshop='QuickStitch'):
    """Retain the explicit order, product and workshop under evaluation."""
    return {'intent':'allocate_request', 'patch_operations':[
        {'op':'set','field':'order_id','value':'ORD-103','quote':'ORD-103'},
        {'op':'set','field':'product','value':'Scarf','quote':'scarves'},
        {'op':'set','field':'preferred_workshop','value':workshop,'quote':workshop}]}


class FeasibilityScript(NativeScript):
    """Script model outputs while exercising actual routing, extraction and services."""
    def __init__(self, candidates, **kwargs):
        super().__init__(order_id='ORD-103', **kwargs)
        self.candidates = candidates
        self.extraction_count = 0

    def invoke_task(self, mode, key, bundle):
        result = self.candidates[min(self.extraction_count,len(self.candidates)-1)]
        self.extraction_count += 1
        self.preparation_prompts.append(bundle.as_messages())
        return {'text':json.dumps(result)}, {}


class WorkshopFeasibilityQuestions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name)/'feasibility.sqlite3')
        self.sid = chat.create(owner='alice',request_id='create',db_path=self.path,
            as_of=date(2026,4,1),mode='llm')['session_id']

    def turn(self, model, message=QUESTION, request_id='check', version=0):
        return chat.turn(self.sid,owner='alice',request_id=request_id,expected_version=version,
                         db_path=self.path,message=message,registry=model)

    def trace(self):
        return chat.execution_trace(self.sid,owner='alice',db_path=self.path)

    def test_exact_question_returns_actual_capability_failure_without_reconfirming_input(self):
        model = FeasibilityScript([candidate()])
        result = self.turn(model)
        self.assertEqual(result['session']['task']['draft']['order_id'],'ORD-103')
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertEqual(result['validation_report']['resolved_fields']['pieces'],2000)
        self.assertTrue(any(i['code']=='PREFERRED_INELIGIBLE' for i in result['issues']))
        self.assertIn('cannot_make_accessories',result['explanation'])
        self.assertNotIn('order ID is missing',result['explanation'])
        self.assertNotIn('Which order',result['explanation'])
        self.assertNotIn('Please confirm',result['explanation'])
        self.assertFalse(model.offered)
        trace=self.trace()
        self.assertEqual(trace['tool_calls'],[])
        calls=[e['detail'] for e in trace['events'] if e['event_type']=='model_call']
        self.assertEqual([c['stage'] for c in calls],['intent','extract'])
        self.assertEqual(calls[0]['prompt']['version'],'v3')
        self.assertEqual(calls[1]['prompt']['version'],'v7')
        self.assertFalse(result['committed'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)

    def test_query_like_inner_intent_with_omitted_facts_is_repaired(self):
        wrong={'intent':'query_workshop','patch_operations':[]}
        model=FeasibilityScript([wrong,candidate()])
        result=self.turn(model)
        self.assertEqual(model.extraction_count,2)
        failures=[e['detail'] for e in self.trace()['events'] if e['event_type']=='extraction_validation_failed']
        self.assertEqual(failures[0]['reason'],'OMITTED_EXPLICIT_ORDER_ID')
        self.assertEqual(failures[0]['expected_fields'],{'order_id':'ORD-103','preferred_workshop':'W1'})
        self.assertIn('cannot_make_accessories',result['explanation'])

    def test_eligible_candidate_question_returns_only_an_uncommitted_preview_and_replays(self):
        text='Nimble Needle for the scarves on ORD-103?'
        model=FeasibilityScript([candidate('Nimble Needle')],actions=actions())
        result=self.turn(model,text)
        self.assertEqual(result['allocation']['order_id'],'ORD-103')
        self.assertEqual(result['allocation']['workshop_id'],'W6')
        self.assertEqual(result['allocation']['allocated_pieces'],2000)
        self.assertFalse(result['committed'])
        replay=self.turn(model,text)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'],result['recommendation_id'])
        self.assertEqual(model.extraction_count,1)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0],1)

    def test_old_missing_order_report_does_not_block_the_next_prepared_check(self):
        with Database(self.path) as db,db.transaction() as c:
            session=chat_repository.snapshot(c,self.sid,'alice')
            task=session['task']
            task.update(state='BLOCKED',report={'blocking_issues':[{'code':'MISSING_ORDER_ID','field':'order_id',
                'severity':'blocking','question':'Which order would you like to allocate?'}]})
            chat_repository.save_task(c,task)
        result=self.turn(FeasibilityScript([candidate()]))
        self.assertIn('cannot_make_accessories',result['explanation'])
        self.assertFalse(any(i['code']=='MISSING_ORDER_ID' for i in result['issues']))

    def test_status_lookup_remains_read_only_and_does_not_require_allocation_fields(self):
        model=NativeScript(intent_text='{"task_type":"compat"}',actions=[AIMessage(content='Order status lookup.')])
        result=self.turn(model,'What is the status of ORD-103?')
        self.assertEqual(model.preparation_prompts,[])
        self.assertIsNone(result['session']['task']['draft']['order_id'])
        self.assertEqual(result['session']['task']['task_version'],0)
        self.assertIsNone(result['recommendation_id'])

    def test_explicit_hypothetical_keeps_an_existing_recommendation_unchanged(self):
        first=self.turn(NativeScript(actions=actions()),'Allocate ORD-045.')
        before=deepcopy(first['session'])
        model=NativeScript(intent_text='{"task_type":"compat"}',
                           actions=[AIMessage(content='This is a hypothetical assessment; no allocation was changed.')])
        result=self.turn(model,'What if QuickStitch handled the scarves on ORD-103?',
                         request_id='hypothetical',version=first['session_version'])
        self.assertEqual(result['session']['task']['draft'],before['task']['draft'])
        self.assertEqual(result['session']['task']['task_version'],before['task']['task_version'])
        self.assertEqual(result['recommendation_id'],before['recommendation']['recommendation_id'])
        self.assertEqual(model.preparation_prompts,[])

    def test_modal_candidate_questions_keep_the_same_grounded_workshop(self):
        from app.services.intake.evidence import candidate_workshop_question
        from app.services.chat.interpretation import rule_interpret
        with Database(self.path) as db:
            context=build_context(db.connection,chat_repository.snapshot(db.connection,self.sid,'alice'))
        for text in ('Can QuickStitch take ORD-103?', 'Could QuickStitch handle ORD-103?',
                     'Would W1 work for ORD-103?', QUESTION):
            with self.subTest(text=text):
                self.assertEqual(candidate_workshop_question(text,context['workshop_names']),'W1')
                baseline=rule_interpret(text,context)
                self.assertEqual(baseline.intent,'allocate_request')
                self.assertTrue(any(p.field=='preferred_workshop' and p.value=='W1' for p in baseline.patch_operations))
                from app.services.chat.extraction import ExtractionValidationError
                with self.assertRaises(ExtractionValidationError):
                    validate_candidate({'intent':'query_workshop','patch_operations':[]},message=text,conversation=context)
        for text in ('What is the status of ORD-103?', 'Is QuickStitch available?',
                     'What if QuickStitch handled ORD-103?', 'QuickStitch or Nimble Needle for ORD-103?'):
            self.assertIsNone(candidate_workshop_question(text,context['workshop_names']))

    def test_offline_modal_question_also_returns_actual_eligibility(self):
        sid=chat.create(owner='alice',request_id='offline',db_path=self.path,
                        as_of=date(2026,4,1),mode='offline')['session_id']
        result=chat.turn(sid,owner='alice',request_id='offline-check',expected_version=0,
                        db_path=self.path,message='Can QuickStitch take ORD-103?')
        self.assertEqual(result['session']['task']['draft']['order_id'],'ORD-103')
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertIn('cannot_make_accessories',result['assistant_message']['content'])
        self.assertFalse(result['committed'])

    def test_pure_order_query_extraction_can_remain_read_only(self):
        with Database(self.path) as db:
            context=build_context(db.connection,chat_repository.snapshot(db.connection,self.sid,'alice'))
        result=validate_candidate({'intent':'query_order','patch_operations':[]},
            message='What is the status of ORD-103?',conversation=context)
        self.assertEqual(result.patch_operations,[])
