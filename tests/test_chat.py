"""Behavioral contracts for Chat v2, shared confirmation and preflight blockers."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from app.db.database import Database, DB_VERSION
from app.services import chat
from app.services.interpretation import rule_interpret, validate_interpretation
from app.llm.registry import ModelRegistry
from app.config.model_settings import ModelSettings, ModelSpec
from app.llm.errors import ModelSelectionError
from app.schemas.chat import TurnInterpretation
from app.main import create_app
from app.config.settings import Settings


class ChatBehavior(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'chat.sqlite3')
        self.counter=0
        self.sid=chat.create(owner='alice',request_id='create',db_path=self.path,as_of=date(2026,4,1),mode='offline')['session_id']

    def inspect(self):
        return chat.inspect(self.sid,owner='alice',db_path=self.path)

    def turn(self,message='',**kwargs):
        self.counter+=1
        args={'owner':'alice','db_path':self.path,'request_id':f'turn-{self.counter}','expected_version':self.inspect()['version'],'message':message}
        args.update(kwargs)
        return chat.turn(self.sid,**args)

    def recommend(self):
        return self.turn('Allocate ORD-045 cheapest; exclude W3.')

    def confirm(self,**kwargs):
        rec=self.inspect()['recommendation']
        return self.turn(action='confirm',recommendation_id=rec['recommendation_id'],**kwargs)

    def scalar(self,sql):
        with Database(self.path) as db:
            return db.connection.execute(sql).fetchone()[0]

    def test_missing_information_never_calls_planner(self):
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            first=self.turn('帮我分配，成本越低越好')
            self.assertFalse(first['validation_report']['ready_for_planning'])
        final=self.turn('ORD-045')
        self.assertEqual(final['session']['task']['draft']['objective'],'min_cost')
        self.assertEqual(final['task_state'],'RECOMMENDED')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),0)

    def test_compound_followup_undo_and_exclusion_removal(self):
        self.recommend()
        self.turn('最多两个工坊，不要 W6')
        self.turn('撤销刚才对工坊数量的修改')
        draft=self.inspect()['task']['draft']
        self.assertIsNone(draft['num_workshop_allowed'])
        self.assertEqual(draft['exclusion'],['W3','W6'])
        self.turn('不排除 W3 了')
        self.assertEqual(self.inspect()['task']['draft']['exclusion'],['W6'])

    def test_conflicting_order_fields_collected_and_explicit_resolution(self):
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            result=self.turn('Allocate ORD-045 cheapest, 999 pieces, due 2027-01-01.')
        fields={p['field'] for p in result['validation_report']['blocking_issues']}
        self.assertTrue({'pieces','due_date'}.issubset(fields))
        result=self.turn('使用登记信息')
        self.assertEqual(result['task_state'],'RECOMMENDED')

    def test_budget_survives_unrelated_updates_and_blocks_confirmation(self):
        self.recommend()
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            self.turn('不要 W6，预算 100 元')
            result=self.turn('改成两个工坊')
        self.assertTrue(result['validation_report']['blocking_issues'])
        with self.assertRaises(chat.ChatError):
            self.confirm()
        result=self.turn('取消预算')
        self.assertEqual(result['task_state'],'RECOMMENDED')

    def test_same_turn_objective_conflict_survives_unrelated_patch(self):
        self.turn('Allocate ORD-045 cheapest and fastest.')
        result=self.turn('改成两个工坊')
        self.assertFalse(result['validation_report']['ready_for_planning'])
        result=self.turn('最低成本')
        self.assertEqual(result['task_state'],'RECOMMENDED')

    def test_unknown_preferred_and_excluded_workshops_block_planner(self):
        for expression in ('Allocate ORD-045 to W99.','Allocate ORD-045; exclude W99.'):
            with self.subTest(expression=expression),patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
                result=self.turn(expression)
                self.assertFalse(result['validation_report']['ready_for_planning'])

    def test_queries_preserve_task_and_do_not_invalidate_recommendation(self):
        self.recommend()
        before=self.inspect()['task']
        rec=self.inspect()['recommendation']['recommendation_id']
        self.turn('为什么选这个工坊？')
        self.turn('ORD-109 现在是什么状态？')
        after=self.inspect()
        self.assertEqual(before,after['task'])
        self.assertEqual(after['recommendation']['recommendation_id'],rec)
        self.assertIn('ORD-109',chat.list_messages(self.sid,owner='alice',db_path=self.path)['items'][-1]['content'])

    def test_workshop_query_is_not_order_lookup(self):
        response=self.turn('工坊 W3 的状态和产能怎么样？')
        self.assertEqual(response['intent'],'query_workshop')
        self.assertIn('Workshop W3',response['assistant_message']['content'])

    def test_order_id_answer_to_query_does_not_become_allocation_request(self):
        self.turn('订单状态怎么样？')
        with patch('app.services.allocation.plan',side_effect=AssertionError('read-only query must not plan')):
            result=self.turn('ORD-045')
        self.assertEqual(result['intent'],'query_order')
        self.assertIsNone(result['session']['task']['draft']['order_id'])
        self.assertIn('ORD-045',result['assistant_message']['content'])

    def test_confirm_with_revision_cannot_commit(self):
        self.recommend()
        old=self.inspect()['recommendation']['recommendation_id']
        result=self.turn('确认，不过不要 W6')
        self.assertFalse(result['committed'])
        self.assertNotEqual(result['recommendation_id'],old)
        self.assertIn('W6',result['session']['task']['draft']['exclusion'])

    def test_new_request_and_owner_isolation(self):
        self.recommend()
        fresh=self.turn('new request')
        self.assertNotEqual(fresh['session_id'],self.sid)
        self.assertIsNone(fresh['session']['task']['draft']['order_id'])
        self.assertEqual(fresh['session']['task']['draft']['exclusion'],[])
        with self.assertRaises(chat.ChatError) as error:
            chat.inspect(self.sid,owner='bob',db_path=self.path)
        self.assertEqual(error.exception.status,404)
        self.assertEqual(chat.list_recommendations(owner='bob',db_path=self.path)['items'],[])

    def test_switch_order_blocks_and_does_not_drop_original_binding(self):
        self.recommend()
        result=self.turn('ORD-109')
        self.assertEqual(result['session']['task']['draft']['order_id'],'ORD-045')
        self.assertFalse(result['validation_report']['ready_for_planning'])

    def test_shared_confirmation_feedback_replay_and_post_commit_chat(self):
        self.recommend()
        approved=self.confirm(request_id='from-workbench')
        self.assertTrue(approved['committed'])
        self.assertIn('Committed 150 pieces of ORD-045',approved['assistant_message']['content'])
        rec=self.inspect()['recommendation']
        replay=self.turn(action='confirm',request_id='from-chat',recommendation_id=rec['recommendation_id'],expected_version=1)
        self.assertTrue(replay['already_executed'])
        self.assertEqual(approved['feedback_message_id'],replay['feedback_message_id'])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM chat_messages WHERE content LIKE 'Committed%'") ,1)
        self.assertEqual(self.inspect()['status'],'OPEN')
        followup=self.turn('最终分了多少？')
        self.assertIn('Committed result',followup['assistant_message']['content'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),1)

    def test_two_entry_points_concurrently_commit_once(self):
        rec=self.recommend()['session']['recommendation']
        version=self.inspect()['version']
        def commit(key):
            return chat.turn(self.sid,owner='alice',db_path=self.path,request_id=key,expected_version=version,action='confirm',recommendation_id=rec['recommendation_id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(commit,['from-chat','from-desk']))
        self.assertTrue(all(r['committed'] for r in responses))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM chat_messages WHERE content LIKE 'Committed%'") ,1)

    def test_queue_change_returns_new_recommendation_without_commit(self):
        old=self.recommend()['recommendation_id']
        with Database(self.path) as db:
            db.connection.execute("UPDATE workshop_queue SET current_queue_days=current_queue_days+2 WHERE workshop_id='W8'")
        result=self.confirm()
        self.assertFalse(result['committed'])
        self.assertEqual(result['http_status'],409)
        self.assertNotEqual(result['recommendation_id'],old)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),0)

    def test_read_refresh_disables_both_entry_points_when_resources_change(self):
        self.recommend()
        with Database(self.path) as db:
            db.connection.execute("UPDATE workshop_queue SET current_queue_days=current_queue_days+2 WHERE workshop_id='W8'")
        self.assertEqual(self.inspect()['recommendation']['status'],'superseded')
        self.assertEqual(chat.list_recommendations(owner='alice',db_path=self.path)['items'][0]['status'],'superseded')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),0)
        self.assertEqual(chat.list_recommendations(owner='alice',db_path=self.path,status='valid')['items'],[])
        self.assertEqual(len(chat.list_recommendations(owner='alice',db_path=self.path,status='superseded')['items']),1)

    def test_sql_failure_rolls_back_business_and_feedback(self):
        self.recommend()
        with Database(self.path) as db:
            db.connection.execute("CREATE TRIGGER fail_chat_feedback BEFORE INSERT ON chat_messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.confirm()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM working_order'),0)
        self.assertEqual(self.scalar("SELECT state FROM orders WHERE order_id='ORD-045'"),'READY')
        self.assertEqual(self.inspect()['recommendation']['status'],'valid')
        self.assertEqual(self.inspect()['task']['state'],'RECOMMENDED')

    def test_idempotency_and_version_conflicts(self):
        result=self.turn('Allocate ORD-045.',request_id='same')
        replay=self.turn('Allocate ORD-045.',request_id='same',expected_version=0)
        self.assertTrue(replay['replayed'])
        self.assertEqual(result['turn_id'],replay['turn_id'])
        with self.assertRaises(chat.ChatError):
            self.turn('不要 W3',request_id='same',expected_version=0)
        with self.assertRaises(chat.ChatError):
            self.turn('不要 W3',expected_version=0)

    def test_creation_with_first_message_replays_without_duplicates(self):
        args=dict(owner='alice',request_id='first',db_path=self.path,as_of=date(2026,4,1),message='Allocate ORD-045.',mode='offline')
        one=chat.create(**args);two=chat.create(**args)
        self.assertEqual(one['session_id'],two['session_id'])
        self.assertTrue(two['replayed'])
        self.assertEqual(len(chat.list_messages(one['session_id'],owner='alice',db_path=self.path)['items']),2)

    def test_missing_queue_data_never_calls_planner(self):
        with Database(self.path) as db:
            db.connection.execute("DELETE FROM workshop_queue WHERE workshop_id='W3'")
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            result=self.recommend()
        self.assertIn('RESOURCE_DATA_ERROR',{p['code'] for p in result['validation_report']['blocking_issues']})

    def test_ambiguous_cancellation_does_not_execute(self):
        self.recommend()
        result=self.turn('取消')
        self.assertFalse(result['committed'])
        self.assertFalse(result['validation_report']['ready_for_planning'])

    def test_hypothetical_does_not_change_formal_constraints(self):
        self.recommend()
        before=self.inspect()['task']
        result=self.turn('如果允许迟交会怎样？')
        self.assertIn('Hypothetical comparison',result['assistant_message']['content'])
        self.assertEqual(before,self.inspect()['task'])

    def test_new_request_with_initial_message_keeps_it_in_new_session(self):
        self.recommend()
        old=self.inspect()['task']
        fresh=self.turn('new request Allocate ORD-109 cheapest.')
        self.assertEqual(fresh['previous_session_id'],self.sid)
        self.assertEqual(fresh['session']['task']['draft']['order_id'],'ORD-109')
        self.assertEqual(fresh['session']['task']['draft']['exclusion'],[])
        self.assertEqual(old,self.inspect()['task'])
        saved=chat.list_messages(fresh['session_id'],owner='alice',db_path=self.path)['items']
        self.assertIn('ORD-109',saved[0]['content'])

    def test_archive_after_commit_preserves_feedback(self):
        self.recommend();approved=self.confirm()
        result=self.turn(action='archive')
        self.assertEqual(result['session']['status'],'ARCHIVED')
        self.assertEqual(result['session']['task']['state'],'CONFIRMED')
        self.assertEqual(result['session']['recommendation']['feedback_message_id'],approved['feedback_message_id'])

    def test_zero_pieces_and_excessive_limit_are_clarification_not_service_errors(self):
        for message in ('分配 ORD-045，0件','Allocate ORD-045; at most nine workshops.'):
            with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
                result=self.turn(message)
            self.assertEqual(result['http_status'],200)
            self.assertFalse(result['validation_report']['ready_for_planning'])

    def test_explicitly_withdrawing_soft_preference_unblocks(self):
        self.turn('分配 ORD-045，优先 W3')
        result=self.turn('取消工坊偏好')
        self.assertEqual(result['task_state'],'RECOMMENDED')

    def test_session_pagination_returns_latest_then_older_without_duplicates(self):
        for index in range(3):
            chat.create(owner='alice',request_id=f'new-{index}',db_path=self.path,as_of=date(2026,4,1),mode='offline')
        one=chat.list_sessions(owner='alice',db_path=self.path,limit=2)
        two=chat.list_sessions(owner='alice',db_path=self.path,limit=2,after=one['next_cursor'])
        self.assertEqual(len({s['session_id'] for s in one['items']+two['items']}),4)
        self.assertEqual(two['items'][-1]['session_id'],self.sid)

    def test_v7_upgrade_and_failed_migration_preserve_business_records(self):
        for fail in (False,True):
            path=str(Path(self.temp.name)/f'v7-{fail}.sqlite3')
            with patch.object(Database,'_upgrade_chat'), patch.object(Database,'_upgrade_agent'):
                with Database(path) as db:
                    self.assertEqual(db.connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],7)
                    before=[tuple(r) for r in db.connection.execute('SELECT * FROM orders')]
                    if fail:
                        db.connection.execute("CREATE TRIGGER fail_v8 BEFORE INSERT ON schema_migrations WHEN NEW.version=8 BEGIN SELECT RAISE(ABORT,'migration test'); END")
            if fail:
                with self.assertRaises(sqlite3.Error):Database(path)
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],7)
                    self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='chat_sessions'").fetchone())
                    self.assertEqual([tuple(r) for r in connection.execute('SELECT * FROM orders')],before)
            else:
                with Database(path) as db:
                    self.assertEqual(db.connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],DB_VERSION)
                    self.assertEqual([tuple(r) for r in db.connection.execute('SELECT * FROM orders')],before)

    def test_query_with_new_budget_is_not_misclassified_as_read_only(self):
        self.recommend()
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            result=self.turn('方案多少钱，预算100元')
        self.assertEqual(result['task_state'],'BLOCKED')
        self.assertTrue(result['session']['task']['issues'])

    def test_currency_cap_cannot_be_silently_dropped(self):
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            result=self.turn('分配 ORD-045，成本最低，但不超过100元')
        self.assertEqual(result['task_state'],'BLOCKED')

    def test_time_window_requires_explicit_supported_constraint(self):
        with patch('app.services.allocation.plan',side_effect=AssertionError('planner must not run')):
            result=self.turn('Allocate ORD-045 within two days.')
        self.assertFalse(result['validation_report']['ready_for_planning'])

    def test_compound_revision_also_answers_why(self):
        self.recommend()
        result=self.turn('不要 W6，为什么推荐这个工坊？')
        self.assertIn('W6',result['session']['task']['draft']['exclusion'])
        self.assertIn('Current recommendation uses',result['assistant_message']['content'])


class ChatAPI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'api.sqlite3')
        self.client=self.enterContext(TestClient(create_app(Settings(db_path=self.path,require_auth=False),
            model_settings=ModelSettings(default_mode='offline'))))

    def test_new_endpoints_and_shared_confirm_restore_message(self):
        create=self.client.post('/api/chat/sessions',json={'request_id':'create','message':'Allocate ORD-045 cheapest.'}).json()
        sid=create['session_id'];rid=create['recommendation_id']
        rec=self.client.get('/api/chat/recommendations').json()['items'][0]
        self.assertEqual(rid,rec['recommendation_id']);self.assertEqual(rec['source'],'chat_v2')
        response=self.client.post(f'/api/chat/sessions/{sid}/turns',json={'request_id':'desk-confirm','expected_version':rec['session_version'],'action':'confirm','recommendation_id':rid})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['committed'])
        history=self.client.get(f'/api/chat/sessions/{sid}/messages').json()['items']
        self.assertIn('Committed',history[-1]['content'])
        self.assertEqual(self.client.get('/api/chat/recommendations').json()['items'][0]['status'],'confirmed')
        for asset in ('/chat','/chat.css','/chat.js','/chat-common.js','/desk-chat.js'):
            self.assertEqual(self.client.get(asset).status_code,200)

    def test_strict_versions_actions_and_pagination(self):
        sid=self.client.post('/api/chat/sessions',json={'request_id':'s'}).json()['session_id']
        for version in ('0',True,-1):
            self.assertEqual(self.client.post(f'/api/chat/sessions/{sid}/turns',json={'request_id':'x','expected_version':version,'message':'hello'}).status_code,400)
        self.assertEqual(self.client.get('/api/chat/sessions?limit=1000').status_code,400)
        self.assertEqual(self.client.post(f'/api/chat/sessions/{sid}/turns',json={'request_id':'x','expected_version':0,'action':'confirm','message':'不要 W3'}).status_code,400)


class ChatModels(unittest.TestCase):
    def test_context_model_protocol_uses_raw_model_and_preserves_history(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=str(Path(temp.name)/'models.sqlite3');calls=[];methods=[]
        class Fake:
            def invoke(self,messages):
                calls.append(messages)
                system=messages[0]['content']
                context=json.loads(system.split('Context: ',1)[1].split('Classify the entire',1)[0])
                value=rule_interpret(messages[-1]['content'],context)
                return AIMessage(content=value.model_dump_json())
        def factory(spec):
            methods.append(spec.output_method);return Fake()
        registry=ModelRegistry(ModelSettings(default_mode='llm',default_model='m',models=(ModelSpec('m','openai','test','mock',output_method='json_schema'),)),factory=factory)
        registry.initialize()
        with self.assertRaises(chat.ChatError) as error:
            chat.create(owner='alice',request_id='one',db_path=path,as_of=date(2026,4,1),registry=registry,message='Allocate cheapest; exclude W3.')
        self.assertEqual(error.exception.code,'TOOLS_UNSUPPORTED')
        self.assertEqual(methods,['json_schema'])
        with Database(path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM chat_agent_runs WHERE status='failed'").fetchone()[0],1)

    def test_forged_or_assistant_evidence_is_rejected(self):
        context={'current_sequence':3,'history':[{'sequence':2,'role':'assistant','content':'ORD-045'}]}
        value=TurnInterpretation(intent='allocate_request',patch_operations=[{'op':'set','field':'order_id','value':'ORD-045','evidence':{'message_sequence':2,'quote':'ORD-045'}}])
        with self.assertRaises(ValueError):
            validate_interpretation(value,'same as before',context)

    def test_hallucinated_quantity_or_constraint_withdrawal_is_rejected(self):
        context={'current_sequence':1,'history':[]}
        forged=TurnInterpretation(intent='modify_constraints',patch_operations=[{'op':'set','field':'pieces','value':999,
            'evidence':{'message_sequence':1,'quote':'allocate ORD-045'}}])
        with self.assertRaisesRegex(ValueError,'UNGROUNDED_QUANTITY'):
            validate_interpretation(forged,'allocate ORD-045',context)
        forged=TurnInterpretation(intent='modify_constraints',answered_question_ids=['unsupported_constraint'])
        with self.assertRaisesRegex(ValueError,'UNGROUNDED_WITHDRAWAL'):
            validate_interpretation(forged,'改成两个工坊',context)


if __name__=='__main__':
    unittest.main()
