"""Contextual alternatives use planner results and pin explicit workshop choices."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage
from app.db.database import Database
from app.db import chat_repository
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate, ExtractionValidationError
from tests.test_alternative_acceptance import AlternativeScript, accept
from tests.test_allocation_node import actions


QUESTION = 'OldMill is free right now — give them ORD-008.'
INITIAL = {'intent':'allocate_request','patch_operations':[
    {'op':'set','field':'order_id','value':'ORD-008','quote':'ORD-008'},
    {'op':'set','field':'preferred_workshop','value':'W7','quote':'OldMill'}]}
VIEW = {'intent':'request_alternatives'}
SELECT = {'intent':'select_workshop','patch_operations':[
    {'op':'set','field':'preferred_workshop','value':'W1','quote':'W1'}]}


class CandidateFollowups(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'candidates.sqlite3')
        self.sid=chat.create(owner='alice',request_id='create',db_path=self.path,
                            as_of=date(2026,4,1),mode='llm')['session_id']

    def turn(self,model,text,request_id,version):
        return chat.turn(self.sid,owner='alice',request_id=request_id,expected_version=version,
                         db_path=self.path,message=text,registry=model)

    def begin(self,followups=None,**kwargs):
        model=AlternativeScript([INITIAL],followups=followups or [VIEW,SELECT],**kwargs)
        first=self.turn(model,QUESTION,'first',0)
        return model,first

    def test_other_options_then_w1_generates_w1_preview_without_committing(self):
        model,first=self.begin(actions=actions())
        before=deepcopy(first['session']['task'])
        other=self.turn(model,'any other options','others',first['session_version'])
        task=other['session']['task']
        for field in ('draft','sources','changes','issues','task_version','state'):
            self.assertEqual(task[field],before[field])
        self.assertEqual(len(other['alternatives']),5)
        by_id={o['plan']['allocation'][0]['workshop_id']:o for o in other['alternatives']}
        self.assertEqual(by_id['W6']['plan']['estimated_delivery_date'],'2026-04-08')
        self.assertEqual(by_id['W6']['plan']['delay_days'],-1)
        self.assertEqual(by_id['W2']['plan']['estimated_delivery_date'],'2026-04-10')
        self.assertEqual(by_id['W2']['plan']['delay_days'],1)
        self.assertTrue(all(o['required_changes']=={'preferred_workshop':wid} for wid,o in by_id.items()))
        self.assertIsNone(other['recommendation_id'])
        history=chat.list_messages(self.sid,owner='alice',db_path=self.path)['items']
        self.assertEqual(history[-1]['metadata']['alternatives'],other['alternatives'])
        replay=self.turn(model,'any other options','others',first['session_version'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['alternatives'],other['alternatives'])
        selected=self.turn(model,'W1 then','select',other['session_version'])
        self.assertEqual(selected['allocation']['workshop_id'],'W1')
        self.assertEqual(selected['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertFalse(selected['committed'])
        self.assertEqual(model.extract_count,1)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)

    def test_option_reference_applies_the_specific_candidate_not_a_generic_relaxation(self):
        model,first=self.begin(actions=actions())
        other=self.turn(model,'who else could do this?','others',first['session_version'])
        index=next(i for i,o in enumerate(other['alternatives']) if o['plan']['allocation'][0]['workshop_id']=='W1')
        model.followups[1]={'intent':'select_workshop','accept_alternative':{},'_choice':index}
        chosen=self.turn(model,f'use option {index+1}','select',other['session_version'])
        self.assertEqual(chosen['allocation']['workshop_id'],'W1')
        self.assertEqual(chosen['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertEqual(chosen['session']['task']['sources']['preferred_workshop']['alternative_id'],other['alternatives'][index]['alternative_id'])

    def test_misread_w1_as_generic_acceptance_is_repaired_before_preparation(self):
        model,first=self.begin(followups=[accept(),SELECT],actions=actions())
        chosen=self.turn(model,'W1 then','select',first['session_version'])
        self.assertEqual(chosen['allocation']['workshop_id'],'W1')
        events=chat.execution_trace(self.sid,owner='alice',db_path=self.path)['events']
        failures=[e for e in events if e['event_type']=='followup_validation_failed']
        self.assertEqual(failures[0]['detail']['reason'],'ALTERNATIVE_WORKSHOP_MISMATCH')
        self.assertEqual(model.followup_count,2)

    def test_explanation_is_read_only_and_does_not_consume_candidates(self):
        model,first=self.begin(followups=[VIEW,{'intent':'explain_recommendation'}],
            actions=[AIMessage(content='The suspended workshop cannot accept this order; the listed candidates preserve your other requirements.')])
        other=self.turn(model,'any other options','others',first['session_version'])
        explained=self.turn(model,'why those workshops?','why',other['session_version'])
        self.assertEqual(explained['session']['task'],other['session']['task'])
        self.assertIsNone(explained['recommendation_id'])
        self.assertEqual(model.extract_count,1)

    def test_viewing_options_preserves_exclusions_and_hard_deadline(self):
        model,first=self.begin()
        with Database(self.path) as db,db.transaction() as c:
            task=chat_repository.snapshot(c,self.sid,'alice')['task']
            task['draft'].update(exclusion=['W1'],deadline_required=True)
            chat_repository.save_task(c,task)
        other=self.turn(model,'any other options','others',first['session_version'])
        self.assertTrue(other['alternatives'])
        self.assertTrue(other['session']['task']['draft']['deadline_required'])
        for option in other['alternatives']:
            self.assertNotEqual(option['plan']['allocation'][0]['workshop_id'],'W1')
            self.assertLessEqual(option['plan']['delay_days'],0)
            self.assertNotIn('deadline_required',option['required_changes'])

    def test_viewing_alternatives_does_not_supersede_a_valid_recommendation(self):
        model,first=self.begin(followups=[SELECT,VIEW],actions=actions())
        chosen=self.turn(model,'W1 then','select',first['session_version'])
        other=self.turn(model,'any other options','others',chosen['session_version'])
        self.assertEqual(other['session']['recommendation']['recommendation_id'],chosen['recommendation_id'])
        self.assertEqual(other['session']['recommendation']['status'],'valid')
        self.assertEqual(other['session']['task']['task_version'],chosen['session']['task']['task_version'])
        self.assertTrue(all(o['plan']['allocation'][0]['workshop_id']!='W1' for o in other['alternatives']))

    def test_query_cannot_smuggle_changes_and_stale_candidates_cannot_be_accepted(self):
        model,first=self.begin()
        other=self.turn(model,'any other options','others',first['session_version'])
        with Database(self.path) as db:
            context=build_context(db.connection,chat_repository.snapshot(db.connection,self.sid,'alice'))
        bad={'intent':'request_alternatives','patch_operations':[
            {'op':'unset','field':'preferred_workshop','value':None,'quote':'clear preferred workshop'}]}
        with self.assertRaises(ExtractionValidationError):
            validate_candidate(bad,message='clear preferred workshop',conversation=context)
        with Database(self.path) as db,db.transaction() as c:
            task=chat_repository.snapshot(c,self.sid,'alice')['task']
            task['draft']['exclusion']=['W1']
            chat_repository.save_task(c,task)
        model.followups[1]=accept()
        result=self.turn(model,'use your suggestion','stale',other['session_version'])
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'],'W7')

    def test_preview_cache_remains_owner_scoped_and_reuses_the_recorded_result(self):
        from app.services.chat.candidate_options import prepare
        model,first=self.begin()
        other=self.turn(model,'any other options','others',first['session_version'])
        saved=prepare(db_path=self.path,session_id=self.sid,owner='alice',request_id='others',as_of=date(2026,4,1))
        self.assertEqual(saved['result']['alternatives'],other['alternatives'])
        with self.assertRaisesRegex(ValueError,'SESSION_NOT_FOUND'):
            prepare(db_path=self.path,session_id=self.sid,owner='bob',request_id='others',as_of=date(2026,4,1))

    def test_explanation_denies_write_tools_and_a_later_selection_still_works(self):
        denied=AIMessage(content='',tool_calls=[{'name':'compute_plan','args':{},'id':'forged-write'}])
        model,first=self.begin(followups=[{'intent':'explain_recommendation'},SELECT],
            actions=[denied,AIMessage(content='The listed option preserves your other requirements.')]+actions())
        explained=self.turn(model,'why that workshop?','why',first['session_version'])
        self.assertEqual(explained['session']['task'],first['session']['task'])
        self.assertTrue(all('compute_plan' not in names and 'record_production_event' not in names for names in model.offered))
        calls=chat.execution_trace(self.sid,owner='alice',db_path=self.path)['tool_calls']
        self.assertEqual(calls[-1]['tool_name'],'compute_plan')
        self.assertFalse(calls[-1]['result']['ok'])
        chosen=self.turn(model,'W1 then','choose',explained['session_version'])
        self.assertEqual(chosen['allocation']['workshop_id'],'W1')
