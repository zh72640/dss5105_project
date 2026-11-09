"""Saved alternative acceptance uses current authorization, fresh facts and preview guards."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage

from app.db.database import Database
from app.db import chat_repository
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.extraction import validate_candidate, ExtractionValidationError
from app.services.chat.allocation_preparation import prepare
from app.services.chat.alternative_acceptance import is_offline_acceptance_request
from tests.test_architecture_alignment import NativeScript
from tests.test_allocation_node import actions


QUESTION = 'QuickStitch for the scarves on ORD-103?'


def inquiry():
    return {'intent':'allocate_request','patch_operations':[
        {'op':'set','field':'order_id','value':'ORD-103','quote':'ORD-103'},
        {'op':'set','field':'preferred_workshop','value':'W1','quote':'QuickStitch'}]}


def accept(choice=None):
    """Script a model decision; choice is a test-selected saved option index."""
    return {'intent':'modify_constraints','accept_alternative':{},'_choice':choice}


class AlternativeScript(NativeScript):
    def __init__(self, candidates=None, *, routes=None, followups=None, **kwargs):
        super().__init__(**kwargs)
        self.candidates = candidates or [inquiry()]
        self.extract_count = 0
        self.routes = routes or ['allocation','followup']
        self.intent_count = 0
        self.followups = followups or [accept()]
        self.followup_prompts = []
        self.followup_count = 0

    def invoke(self, messages):
        system = messages[0]['content'] if isinstance(messages[0],dict) else messages[0].content
        if 'Classify the current user message' in system:
            route = self.routes[min(self.intent_count,len(self.routes)-1)]
            self.intent_count += 1
            return AIMessage(content=json.dumps({'task_type':route}))
        if "Resolve the user's follow-up" in system:
            self.followup_prompts.append(messages)
            response = deepcopy(self.followups[min(self.followup_count,len(self.followups)-1)])
            self.followup_count += 1
            choice = response.pop('_choice',None)
            if 'accept_alternative' in response:
                marker = 'Current task, pending questions, saved offers and bounded prior messages:'
                context = json.loads(system.split(marker)[1].strip())
                quote = messages[-1]['content'] if isinstance(messages[-1],dict) else messages[-1].content
                ref = response['accept_alternative']
                ref.setdefault('quote',quote)
                options = context['pending_alternatives']
                ref.setdefault('alternative_id', options[choice]['alternative_id'] if choice is not None else None)
                legacy = {'There is no clear suggestion in the current message to accept.',
                          'It is unclear what requirement is being withdrawn.',
                          'No saved suggestion is available in the supplied context, so the suggested workshop cannot be identified.'}
                ref.setdefault('resolved_reference_issue_ids',[q['question_id'] for q in context['pending_questions']
                    if q.get('code') == 'AMBIGUOUS_MESSAGE' and q.get('question') in legacy])
            return AIMessage(content=json.dumps(response))
        return super().invoke(messages)

    def invoke_task(self, mode, key, bundle):
        self.preparation_prompts.append(bundle.as_messages())
        candidate = self.candidates[min(self.extract_count,len(self.candidates)-1)]
        self.extract_count += 1
        return {'text':json.dumps(candidate)}, {}


class AlternativeAcceptanceBehavior(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'alternatives.sqlite3')
        self.sid=chat.create(owner='alice',request_id='create',db_path=self.path,
            as_of=date(2026,4,1),mode='llm')['session_id']

    def turn(self, model, text=QUESTION, request_id='ask', version=0):
        return chat.turn(self.sid,owner='alice',request_id=request_id,expected_version=version,
                         db_path=self.path,message=text,registry=model)

    def first(self):
        model=AlternativeScript(actions=actions())
        first=self.turn(model)
        self.assertEqual(len(first['session']['task']['report']['pending_alternatives']),1)
        return model,first

    def no_work(self):
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0],0)

    def test_unique_suggestion_is_accepted_recomputed_saved_and_only_then_confirmable(self):
        model,first=self.first()
        offered=first['session']['task']['report']['pending_alternatives'][0]
        before_queues=None
        with Database(self.path) as db:
            before_queues=[tuple(r) for r in db.connection.execute('SELECT * FROM workshop_queue ORDER BY workshop_id')]
        second=self.turn(model,'okay use your suggestion','accept',first['session_version'])
        self.assertEqual(second['task_state'],'RECOMMENDED')
        self.assertIsNone(second['session']['task']['draft']['preferred_workshop'])
        self.assertIsNotNone(second['recommendation_id'])
        self.assertFalse(second['committed'])
        self.assertEqual(model.extract_count,1)
        self.assertEqual(model.followup_count,1)  # LLM resolves the follow-up before allocation.
        self.assertEqual(second['allocation']['workshop_id'],offered['plan']['allocation'][0]['workshop_id'])
        source=second['session']['task']['sources']['preferred_workshop']
        self.assertEqual(source['alternative_id'],offered['alternative_id'])
        self.assertEqual(source['quote'],'okay use your suggestion')
        self.assertEqual(second['session']['task']['report']['pending_alternatives'],[])
        replay=self.turn(model,'okay use your suggestion','accept',first['session_version'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'],second['recommendation_id'])
        with Database(self.path) as db:
            self.assertEqual([tuple(r) for r in db.connection.execute('SELECT * FROM workshop_queue ORDER BY workshop_id')],before_queues)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0],1)
        self.no_work()
        confirmed=chat.turn(self.sid,owner='alice',request_id='confirm',expected_version=second['session_version'],
            db_path=self.path,action='confirm',recommendation_id=second['recommendation_id'])
        self.assertTrue(confirmed['committed'])

    def test_a_later_offer_survives_clarification_after_an_earlier_acceptance(self):
        bad={'intent':'unsupported_or_ambiguous','patch_operations':[],
             'ambiguity_reason':'There is no clear suggestion in the current message to accept.'}
        model=AlternativeScript([inquiry(),inquiry()], routes=['allocation','followup','allocation','followup','followup'],
            followups=[accept(),bad,accept()],actions=actions()+actions())
        first=self.turn(model)
        accepted=self.turn(model,'use your suggestion','accept1',first['session_version'])
        again=self.turn(model,QUESTION,'ask-again',accepted['session_version'])
        option_id=again['session']['task']['report']['pending_alternatives'][0]['alternative_id']
        unclear=self.turn(model,'hmm','unclear-again',again['session_version'])
        self.assertEqual(unclear['session']['task']['report']['pending_alternatives'][0]['alternative_id'],option_id)
        second=self.turn(model,'use your suggestion','accept2',unclear['session_version'])
        self.assertEqual(second['task_state'],'RECOMMENDED')
        self.assertEqual(second['session']['task']['issues'],[])
        self.no_work()

    def test_history_and_pending_options_reach_the_extraction_prompt(self):
        ambiguous={'intent':'unsupported_or_ambiguous','patch_operations':[],
                   'ambiguity_reason':'Please clarify your question.'}
        model=AlternativeScript(followups=[ambiguous])
        first=self.turn(model)
        self.turn(model,'Can you explain that suggestion?','explain',first['session_version'])
        system=model.followup_prompts[-1][0]['content']
        option_id=first['session']['task']['report']['pending_alternatives'][0]['alternative_id']
        self.assertIn('"history"',system)
        self.assertIn(first['assistant_message']['content'].split('.')[0],system)
        self.assertIn(option_id,system)
        self.assertIn('"pending_alternatives"',system)

    def test_suggested_workshop_reply_resolves_suspended_oldmill_then_allocates(self):
        question = 'OldMill is free right now — give them ORD-008.'
        candidate = {'intent':'allocate_request','patch_operations':[
            {'op':'set','field':'order_id','value':'ORD-008','quote':'ORD-008'},
            {'op':'set','field':'preferred_workshop','value':'W7','quote':'OldMill'}]}
        model = AlternativeScript([candidate], actions=actions())
        first = self.turn(model, question)
        self.assertIn('status_suspended', first['explanation'])
        second = self.turn(model, 'sure, use your suggested workshop', 'accept', first['session_version'])
        self.assertEqual(second['task_state'],'RECOMMENDED')
        self.assertEqual(second['allocation']['order_id'],'ORD-008')
        self.assertNotEqual(second['allocation']['workshop_id'],'W7')
        self.assertIsNone(second['session']['task']['draft']['preferred_workshop'])
        self.assertEqual(model.extract_count,1)
        self.assertEqual(model.followup_count,1)
        events=chat.execution_trace(self.sid,owner='alice',db_path=self.path)['events']
        calls=[e['detail']['stage'] for e in events if e['event_type']=='model_call']
        self.assertEqual(calls[:4],['intent','extract','intent','followup'])
        self.no_work()

    def test_followup_is_semantic_and_not_gated_by_an_offline_phrase_whitelist(self):
        for index,text in enumerate(('that alternative works for me','please proceed with the workshop you recommended')):
            with self.subTest(text=text):
                self.sid=chat.create(owner='alice',request_id=f'create-{index}',db_path=self.path,
                    as_of=date(2026,4,1),mode='llm')['session_id']
                model=AlternativeScript(actions=actions())
                first=self.turn(model,request_id=f'ask-{index}')
                second=self.turn(model,text,f'accept-{index}',first['session_version'])
                self.assertEqual(second['task_state'],'RECOMMENDED')
                self.assertEqual(second['session']['task']['sources']['preferred_workshop']['quote'],text)
                self.assertEqual(model.followup_count,1)
                self.no_work()

    def test_unclear_or_negative_followup_does_not_persist_a_business_blocker(self):
        decision={'intent':'unsupported_or_ambiguous','ambiguity_reason':'Which alternative do you mean?'}
        model=AlternativeScript(followups=[decision,accept()],actions=actions())
        first=self.turn(model)
        old_task=deepcopy(first['session']['task'])
        second=self.turn(model,"Don't use that workshop; which other option?",'clarify',first['session_version'])
        self.assertEqual(second['session']['task'],old_task)
        self.assertIsNone(second['recommendation_id'])
        third=self.turn(model,'that alternative works for me','accept',second['session_version'])
        self.assertEqual(third['task_state'],'RECOMMENDED')
        self.no_work()

    def test_explanation_followup_routes_to_read_only_compat_without_allocation(self):
        model=AlternativeScript(followups=[{'intent':'explain_recommendation'}],
            actions=[AIMessage(content='The named workshop cannot make accessories; the option removes that sole-workshop restriction.')])
        first=self.turn(model)
        old_task=deepcopy(first['session']['task'])
        result=self.turn(model,'why that workshop?','explain',first['session_version'])
        self.assertEqual(result['session']['task'],old_task)
        self.assertEqual(model.followup_count,1)
        self.assertEqual(model.extract_count,1)
        self.no_work()

    def test_followup_revisions_reuse_current_evidence_without_a_second_extraction(self):
        decision={'intent':'modify_constraints','patch_operations':[
            {'op':'unset','field':'preferred_workshop','value':None,'quote':'remove the required workshop'},
            {'op':'add','field':'exclusion','value':['W4'],'quote':'exclude W4'}]}
        model=AlternativeScript(followups=[decision],actions=actions())
        first=self.turn(model)
        result=self.turn(model,'remove the required workshop and exclude W4','revise',first['session_version'])
        self.assertEqual(result['task_state'],'RECOMMENDED')
        self.assertEqual(result['session']['task']['draft']['exclusion'],['W4'])
        self.assertEqual(model.extract_count,1)
        self.no_work()

    def test_followup_model_response_survives_a_crash_before_node_completion(self):
        from app.agent.intake import interpret_current_message
        model,first=self.first()
        def interrupted(*args,**kwargs):
            interpret_current_message(*args,**kwargs)
            raise RuntimeError('interrupted after model response')
        with patch('app.agent.followup.interpret_current_message',side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError,'interrupted after model response'):
                self.turn(model,'sure, use your suggested workshop','accept',first['session_version'])
        resumed=self.turn(model,'sure, use your suggested workshop','accept',first['session_version'])
        self.assertEqual(resumed['task_state'],'RECOMMENDED')
        self.assertEqual(model.followup_count,1)
        self.no_work()

    def test_followup_uses_the_current_provider_structured_output_contract(self):
        model=AlternativeScript(output_method='json_schema',actions=actions())
        first=self.turn(model)
        result=self.turn(model,'sure, use your suggested workshop','accept',first['session_version'])
        self.assertEqual(result['task_state'],'RECOMMENDED')
        self.assertEqual(model.followup_count,1)
        self.assertTrue(all(binding[1] == 'json_schema' for binding in model.structured_bindings))
        self.no_work()

    def test_followup_repairs_a_partial_quote_instead_of_applying_it(self):
        partial={'intent':'modify_constraints','accept_alternative':{'quote':'suggested workshop'}}
        model=AlternativeScript(followups=[partial,accept()],actions=actions())
        first=self.turn(model)
        result=self.turn(model,'sure, use your suggested workshop','accept',first['session_version'])
        self.assertEqual(result['task_state'],'RECOMMENDED')
        self.assertEqual(model.followup_count,2)
        events=chat.execution_trace(self.sid,owner='alice',db_path=self.path)['events']
        failures=[e for e in events if e['event_type']=='followup_validation_failed']
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]['detail']['reason'],'UNGROUNDED_ALTERNATIVE_ACCEPTANCE')
        self.no_work()

    def test_successfully_prepared_acceptance_cannot_be_recovered_as_an_old_pending_offer(self):
        from app.services.chat.alternative_acceptance import pending_options
        model,first=self.first()
        accepted=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertEqual(accepted['task_state'],'RECOMMENDED')
        with Database(self.path) as db,db.transaction() as c:
            task=chat_repository.snapshot(c,self.sid,'alice')['task']
            task['draft']['preferred_workshop']='W1'
            task['state']='BLOCKED'
            task['issues']=[{'code':'AMBIGUOUS_MESSAGE','field':'message','severity':'blocking',
                            'question':'There is no clear suggestion in the current message to accept.'}]
            self.assertEqual(pending_options(c,task),[])
        self.no_work()

    def test_legacy_uncompleted_acceptance_recovers_after_the_original_constraint_is_restored(self):
        bad={'intent':'unsupported_or_ambiguous','ambiguity_reason':
            'No saved suggestion is available in the supplied context, so the suggested workshop cannot be identified.'}
        uncorrected={'intent':'modify_constraints','accept_alternative':{'resolved_reference_issue_ids':[]}}
        model=AlternativeScript([inquiry(),bad,inquiry()],
            routes=['allocation','allocation','followup','allocation','followup'],
            followups=[uncorrected,accept()],actions=actions())
        first=self.turn(model)
        failed=self.turn(model,'sure, use your suggested workshop','old-failure',first['session_version'])
        consumed=self.turn(model,'follow your previous suggestion','old-accept',failed['session_version'])
        self.assertIsNone(consumed['session']['task']['draft']['preferred_workshop'])
        self.assertEqual(consumed['task_state'],'BLOCKED')
        restored=self.turn(model,QUESTION,'restore',consumed['session_version'])
        accepted=self.turn(model,'sure, use your suggested workshop','retry',restored['session_version'])
        self.assertEqual(accepted['task_state'],'RECOMMENDED')
        self.assertEqual(accepted['session']['task']['issues'],[])
        self.no_work()

    def test_reference_errors_do_not_erase_pending_options_and_resolve_when_accepted(self):
        bad1={'intent':'unsupported_or_ambiguous','patch_operations':[],
              'ambiguity_reason':'There is no clear suggestion in the current message to accept.'}
        bad2={'intent':'unsupported_or_ambiguous','patch_operations':[],
              'ambiguity_reason':'It is unclear what requirement is being withdrawn.'}
        model=AlternativeScript([inquiry(),bad1,bad2],routes=['allocation','allocation','allocation','followup'],actions=actions())
        first=self.turn(model)
        old_id=first['session']['task']['report']['pending_alternatives'][0]['alternative_id']
        second=self.turn(model,'hmm','unclear1',first['session_version'])
        third=self.turn(model,'okay no requirement','unclear2',second['session_version'])
        self.assertEqual(third['session']['task']['report']['pending_alternatives'][0]['alternative_id'],old_id)
        accepted=self.turn(model,'okay use your suggestion','accept',third['session_version'])
        self.assertEqual(accepted['task_state'],'RECOMMENDED')
        self.assertEqual(accepted['session']['task']['issues'],[])
        self.no_work()

    def test_legacy_session_recovers_the_offer_from_preparation_audit(self):
        model,first=self.first()
        with Database(self.path) as db,db.transaction() as c:
            session=chat_repository.snapshot(c,self.sid,'alice')
            task=session['task']
            task['report']={'blocking_issues':[]}
            task['issues']=[{'code':'AMBIGUOUS_MESSAGE','field':'message','severity':'blocking',
                'question':'There is no clear suggestion in the current message to accept.'}]
            chat_repository.save_task(c,task)
            for row in c.execute("SELECT event_id,detail_json FROM chat_agent_events WHERE session_id=? AND event_type='allocation_prepared'",(self.sid,)).fetchall():
                detail=json.loads(row['detail_json'])
                detail['task']['report'].pop('pending_alternatives',None)
                c.execute('UPDATE chat_agent_events SET detail_json=? WHERE event_id=?',(json.dumps(detail),row['event_id']))
        result=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertEqual(result['task_state'],'RECOMMENDED')
        self.assertEqual(result['session']['task']['issues'],[])
        self.no_work()

    def test_fresh_business_facts_replace_old_estimates_without_reusing_the_proposal_plan(self):
        model,first=self.first()
        old_cost=first['session']['task']['report']['pending_alternatives'][0]['plan']['estimated_cost']
        with Database(self.path) as db,db.transaction() as c:
            c.execute('UPDATE workshops SET cost_per_piece=cost_per_piece*2')
        accepted=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertEqual(accepted['allocation']['estimated_cost'],old_cost*2)
        self.assertFalse(accepted['committed'])
        self.no_work()

    def test_changed_requirements_invalidate_old_references(self):
        model,first=self.first()
        with Database(self.path) as db,db.transaction() as c:
            session=chat_repository.snapshot(c,self.sid,'alice')
            session['task']['draft']['exclusion']=['W3']
            chat_repository.save_task(c,session['task'])
        result=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertIn('No current alternative',result['explanation'])
        self.no_work()

    def test_unrelated_budget_issue_is_not_cleared_by_acceptance(self):
        model,first=self.first()
        with Database(self.path) as db,db.transaction() as c:
            session=chat_repository.snapshot(c,self.sid,'alice')
            session['task']['issues'].append({'code':'unsupported_constraint','field':'unsupported',
                'severity':'blocking','question':'The budget requirement remains unresolved.'})
            chat_repository.save_task(c,session['task'])
        result=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertIsNone(result['session']['task']['draft']['preferred_workshop'])
        self.assertIsNone(result['recommendation_id'])
        self.assertIn('budget requirement',result['explanation'])
        self.no_work()

    def test_model_acceptance_reference_cannot_bypass_current_quote_or_selection(self):
        model,first=self.first()
        with Database(self.path) as db:
            session=chat_repository.snapshot(db.connection,self.sid,'alice')
            context=build_context(db.connection,session)
        for message,quote in (("Don't use your suggestion.",'use your suggestion'),
                              ('Can I use your suggestion?','use your suggestion')):
            with self.subTest(message=message),self.assertRaises(ExtractionValidationError):
                validate_candidate({'intent':'modify_constraints','accept_alternative':{'quote':quote}},
                                   message=message,conversation=context)
        reference={'intent':'modify_constraints','accept_alternative':{'alternative_id':'alt-deadbeef','quote':'use your suggestion'}}
        checked=validate_candidate(reference,message='use your suggestion',conversation=context)
        result=prepare(db_path=self.path,session_id=self.sid,owner='alice',request_id='bad-id',
            interpretation=checked,as_of=date(2026,4,1),sequence=3,user_message='use your suggestion')
        self.assertEqual(result['task']['draft']['preferred_workshop'],'W1')
        self.assertTrue(any(i['code']=='ALTERNATIVE_STALE' for i in result['issues']))
        self.no_work()

    def test_multiple_options_require_a_choice_and_then_accept_one(self):
        with Database(self.path) as db,db.transaction() as c:
            c.execute("UPDATE orders SET due_date='2026-04-02' WHERE order_id='ORD-103'")
        value=inquiry()
        value['patch_operations'] += [
            {'op':'set','field':'objective','value':'min_cost','quote':'lowest cost'},
            {'op':'set','field':'deadline_required','value':True,'quote':'must arrive on time'}]
        model=AlternativeScript([value],followups=[accept(),accept(0)],actions=actions())
        first=self.turn(model,'QuickStitch for the scarves on ORD-103, lowest cost; must arrive on time.')
        offers=first['session']['task']['report']['pending_alternatives']
        self.assertGreater(len(offers),1)
        blocked=self.turn(model,'use your suggestion','vague',first['session_version'])
        self.assertIsNone(blocked['recommendation_id'])
        self.assertEqual(blocked['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertIn('multiple alternatives',blocked['explanation'])
        selected=self.turn(model,'use the first option','selected',blocked['session_version'])
        self.assertEqual(selected['task_state'],'RECOMMENDED')
        self.assertFalse(selected['session']['task']['draft']['deadline_required'])
        self.assertEqual(selected['session']['task']['draft']['objective'],'min_cost')
        self.no_work()

    def test_llm_cannot_accept_a_split_only_offline_alternative(self):
        with Database(self.path) as db,db.transaction() as c:
            c.execute('UPDATE workshops SET max_batch_pieces=1000')
        model,first=self.first()
        self.assertEqual(first['session']['task']['report']['pending_alternatives'][0]['supported_mode'],'offline')
        result=self.turn(model,'use your suggestion','accept',first['session_version'])
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['session']['task']['draft']['preferred_workshop'],'W1')
        self.assertTrue(any(i['code']=='ALTERNATIVE_MODE_UNSUPPORTED' for i in result['issues']))
        self.no_work()

    def test_offline_mode_accepts_the_same_conditional_change_and_keeps_exclusions(self):
        first=chat.create(owner='alice',request_id='offline',db_path=self.path,as_of=date(2026,4,1),
            mode='offline',message='Allocate ORD-103 to QuickStitch; exclude W4.')
        second=chat.turn(first['session_id'],owner='alice',request_id='offline-accept',
            expected_version=first['session_version'],db_path=self.path,message='okay use your suggestion')
        self.assertEqual(second['task_state'],'RECOMMENDED')
        self.assertEqual(second['session']['task']['draft']['exclusion'],['W4'])
        self.assertIsNone(second['session']['task']['draft']['preferred_workshop'])
        self.assertFalse(second['committed'])
        self.no_work()

    def test_acceptance_grammar_excludes_unconditional_yes_negation_and_hypotheticals(self):
        for text in ('okay use your suggestion','Use option 1.','yes, go with the second alternative.',
                     'sure, use your suggested workshop'):
            self.assertTrue(is_offline_acceptance_request(text))
        for text in ('yes',"Don't use your suggestion.",'Can I use your suggestion?',
                     'If possible use your suggestion.','use your suggestion and remove the budget'):
            self.assertFalse(is_offline_acceptance_request(text))
