"""Separate explanation and deterministic response nodes, with mocked model calls."""
from contextlib import closing
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent import explanation, main_graph, response, runtime
from app.config.model_settings import ModelSettings, ModelSpec
from app.config.settings import Settings
from app.db.database import Database
from app.llm.errors import BackendError
from app.main import create_app
from app.services.allocation.contracts import saved_result
from app.services.chat import presentation, service as chat
from tests.test_allocation_node import actions
from tests.test_architecture_alignment import NativeScript


class ExplanationScript(NativeScript):
    def __init__(self, *, before_explanation=None, **kwargs):
        super().__init__(**kwargs)
        self.before_explanation = before_explanation
        self.explanation_prompts = []
        self.explanation_messages = []

    def invoke(self, messages):
        system = messages[0]['content'] if isinstance(messages[0], dict) else messages[0].content
        if 'Explain the allocation result' in system:
            self.explanation_prompts.append(system)
            self.explanation_messages.append(deepcopy(messages))
            if self.before_explanation:
                self.before_explanation()
        return super().invoke(messages)


class ExplanationResponseBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'presentation.sqlite3')
        self.sid = chat.create(owner='alice', request_id='create', db_path=self.path,
                               as_of=date(2026, 4, 1), mode='llm')['session_id']

    def turn(self, model, *, request_id='allocate', version=0, text='Allocate ORD-045.'):
        return chat.turn(self.sid, owner='alice', request_id=request_id, expected_version=version,
                         db_path=self.path, message=text, registry=model)

    def checkpoint(self, *, legacy=False):
        with closing(sqlite3.connect(self.path, check_same_thread=False)) as connection:
            factory = main_graph.build_v1_graph if legacy else main_graph.build_graph
            return factory(SqliteSaver(connection)).get_state({
                'configurable': {'thread_id': 'chat-agent:' + self.sid}})

    def trace(self):
        return chat.execution_trace(self.sid, owner='alice', db_path=self.path)

    def test_success_passes_provenance_and_returns_text_with_unchanged_recommendation(self):
        model = ExplanationScript(actions=actions())
        result = self.turn(model)
        state = self.checkpoint().values
        self.assertEqual(state['workflow_version'], 'main_v2')
        self.assertEqual(state['source_node'], 'allocation')
        self.assertEqual(result['type'], 'allocation')
        self.assertEqual(result['explanation'], result['assistant_message']['content'])
        self.assertEqual(result['explanation'], state['explanation']['text'])
        self.assertEqual(result['allocation'], state['task_result']['result'])
        self.assertEqual(result['allocation'], saved_result(result['cards'][0]))
        self.assertEqual(result['recommendation_id'], result['allocation']['recommendation_id'])
        self.assertEqual(len(model.explanation_prompts), 1)
        messages = model.explanation_messages[0]
        self.assertEqual([item['role'] for item in messages], ['system', 'user'])
        self.assertIn('Explain the allocation result', messages[0]['content'])
        self.assertNotIn(result['recommendation_id'], messages[0]['content'])
        self.assertNotIn('ORD-045', messages[0]['content'])
        user_result = json.loads(messages[1]['content'])
        self.assertEqual(user_result, state['task_result'])
        self.assertNotIn('source_node', user_result)
        self.assertEqual(user_result['result']['recommendation_id'], result['recommendation_id'])
        evidence = user_result['result']['explanation_evidence']
        self.assertEqual(evidence, result['cards'][0]['result']['explanation_evidence'])
        self.assertTrue(evidence['candidates'])
        self.assertIn('Minimize completion days', evidence['score_formula'])
        for heading in ('Allocation plan:', 'Allocation method:', 'Why this recommendation:', 'Review before allocation:'):
            self.assertIn(heading, messages[0]['content'])
        self.assertEqual(len(model.offered), 3)
        calls = [item['detail'] for item in self.trace()['events'] if item['event_type'] == 'model_call']
        self.assertEqual([item['stage'] for item in calls],
                         ['intent', 'extract', 'tool_loop', 'tool_loop', 'tool_loop', 'explanation'])
        self.assertEqual(calls[-1]['prompt']['id'], 'allocation.explain')
        self.assertEqual(calls[-1]['prompt']['version'], 'v3')

    def test_gemini_explanation_contains_user_content_without_a_network_call(self):
        from langchain_core.messages import convert_to_messages
        from langchain_google_genai.chat_models import _parse_chat_history
        from google.genai import _transformers

        class GeminiScript(ExplanationScript):
            def invoke(self, messages):
                system_text = messages[0]['content'] if isinstance(messages[0], dict) else messages[0].content
                if 'Explain the allocation result' in system_text:
                    system, contents = _parse_chat_history(convert_to_messages(messages),
                        model='gemini-3.5-flash-lite')
                    self.gemini_has_system = system is not None
                    self.gemini_contents = _transformers.t_contents(contents)
                return super().invoke(messages)

        model = GeminiScript(provider='gemini', actions=actions())
        result = self.turn(model)
        self.assertTrue(model.gemini_has_system)
        self.assertEqual(len(model.gemini_contents), 1)
        self.assertEqual(model.gemini_contents[0].role, 'user')
        self.assertIsNotNone(result['allocation'])
        self.assertTrue(result['explanation'])

    def test_missing_content_error_recovers_without_repeating_saved_allocation(self):
        def missing_content():
            raise ValueError('contents are required.')
        model = ExplanationScript(provider='gemini', actions=actions(), before_explanation=missing_content)
        with self.assertRaises(chat.ChatError) as failed:
            self.turn(model)
        self.assertEqual(failed.exception.code, 'MODEL_REQUEST_FAILED')
        self.assertEqual(failed.exception.details['model_error']['code'], 'gemini_invalid_input')
        self.assertFalse(failed.exception.details['retryable'])
        self.assertNotIn('configuration', str(failed.exception))
        self.assertEqual(self.checkpoint().next, ('explanation',))
        before = deepcopy(self.checkpoint().values['task_result'])
        model.before_explanation = None
        result = self.turn(model)
        self.assertEqual(result['allocation'], before['result'])
        self.assertEqual(len(model.preparation_prompts), 1)
        self.assertEqual(len(self.trace()['tool_calls']), 3)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0], 1)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)

    def test_response_node_is_deterministic_and_preserves_input(self):
        self.turn(ExplanationScript(actions=actions()))
        state = self.checkpoint().values
        before = deepcopy(state['task_result'])
        with patch.object(explanation, 'get_registry', side_effect=AssertionError('No model or prompt')):
            first = response.assemble(state)
            second = response.assemble(state)
        self.assertEqual(first, second)
        self.assertEqual(state['task_result'], before)
        first['response']['allocation']['warnings'].append('CHANGED_COPY')
        self.assertEqual(state['task_result'], before)

    def test_blocked_allocation_skips_explanation_model_and_has_no_card(self):
        model = ExplanationScript(order_id=None)
        result = self.turn(model, text='Allocate an order.')
        self.assertEqual(result['type'], 'allocation')
        self.assertIsNone(result['allocation'])
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['cards'], [])
        self.assertTrue(result['issues'])
        self.assertEqual(result['explanation'], result['assistant_message']['content'])
        self.assertFalse(model.explanation_prompts)

    def test_failed_allocation_uses_its_exact_error_without_explanation_model(self):
        model = ExplanationScript(pieces='150')
        result = self.turn(model, text='Allocate ORD-045, 150 pieces.')
        self.assertEqual(result['issues'][0]['code'], 'EXTRACTION_FORMAT_INVALID')
        self.assertEqual(result['explanation'], 'Extracted field format validation failed for pieces.')
        self.assertIsNone(result['allocation'])
        self.assertFalse(model.explanation_prompts)

    def test_explanation_failure_recovers_at_same_node_and_replay_keeps_both_outputs(self):
        def unavailable():
            raise BackendError('temporary_failure')
        model = ExplanationScript(actions=actions(), before_explanation=unavailable)
        with self.assertRaises(chat.ChatError) as failed:
            self.turn(model)
        self.assertEqual(failed.exception.code, 'MODEL_UNAVAILABLE')
        state = self.checkpoint()
        self.assertEqual(state.next, ('explanation',))
        self.assertIsNone(state.values['response'])
        self.assertEqual(len(self.trace()['tool_calls']), 3)
        model.before_explanation = None
        result = self.turn(model)
        replay = self.turn(ExplanationScript())
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['allocation'], result['allocation'])
        self.assertEqual(replay['explanation'], result['explanation'])
        self.assertEqual(len(model.preparation_prompts), 1)
        self.assertEqual(len(self.trace()['tool_calls']), 3)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM chat_recommendations').fetchone()[0], 1)

    def test_response_node_retry_does_not_repeat_explanation(self):
        model = ExplanationScript(actions=actions())
        with patch.object(main_graph, 'assemble', side_effect=RuntimeError('interrupted packaging')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted packaging'):
                self.turn(model)
        self.assertEqual(self.checkpoint().next, ('response',))
        result = self.turn(model)
        self.assertIsNotNone(result['allocation'])
        self.assertEqual(len(model.explanation_prompts), 1)
        self.assertEqual(len(self.trace()['tool_calls']), 3)

    def test_explanation_tool_call_is_rejected_without_execution(self):
        model = ExplanationScript(actions=[*actions()[:3], AIMessage(content='', tool_calls=[{
            'name': 'compute_plan', 'args': {}, 'id': 'forged-explanation-call'}])])
        with self.assertRaises(chat.ChatError):
            self.turn(model)
        self.assertEqual(len(self.trace()['tool_calls']), 3)
        errors = [item['detail'] for item in self.trace()['events'] if item['event_type'] == 'execution_error']
        self.assertEqual(errors[-1]['code'], 'explanation_unexpected_tools')

    def test_unusable_explanations_remain_model_errors_and_never_become_business_failures(self):
        for text in ('', '这是推荐。'):
            with self.subTest(text=text):
                request_id = 'unusable-' + str(len(text))
                model = ExplanationScript(actions=[*actions()[:3], AIMessage(content=text)])
                with self.assertRaises(chat.ChatError):
                    self.turn(model, request_id=request_id)
                self.assertEqual(self.checkpoint().values['task_result']['status'], 'waiting_user')
                model.actions = [AIMessage(content='Review the saved recommendation.')]
                result = self.turn(model, request_id=request_id)
                self.assertIsNotNone(result['allocation'])
                self.sid = chat.create(owner='alice', request_id='next-' + str(len(text)),
                    db_path=self.path, as_of=date(2026, 4, 1), mode='llm')['session_id']

    def test_changed_facts_during_explanation_remove_old_text_result_and_card(self):
        def change_queue():
            with Database(self.path) as db, db.transaction() as connection:
                connection.execute('UPDATE workshop_queue SET current_queue_days=current_queue_days+2')
        model = ExplanationScript(actions=actions(), before_explanation=change_queue)
        result = self.turn(model)
        self.assertEqual(result['explanation'], presentation.STALE_MESSAGE)
        self.assertEqual(result['assistant_message']['content'], presentation.STALE_MESSAGE)
        self.assertIsNone(result['allocation'])
        self.assertIsNone(result['recommendation_id'])
        self.assertEqual(result['cards'], [])
        self.assertEqual(result['issues'][0]['code'], 'RECOMMENDATION_STALE')
        self.assertEqual(result['session']['recommendation']['status'], 'superseded')
        with Database(self.path) as db:
            row = db.connection.execute("SELECT content,metadata_json FROM chat_messages WHERE role='assistant'").fetchone()
        self.assertEqual(row['content'], presentation.STALE_MESSAGE)
        self.assertIsNone(json.loads(row['metadata_json'])['recommendation_id'])
        replay = self.turn(ExplanationScript())
        self.assertEqual(replay['explanation'], presentation.STALE_MESSAGE)
        self.assertIsNone(replay['allocation'])

    def test_other_sources_are_not_routed_to_allocation_handlers(self):
        for source, task_type in (('order_query', 'order_query'), ('compat', 'allocation')):
            state = {'source_node': source, 'task_result': {'task_type': task_type, 'status': 'blocked',
                'task_id': 'task', 'result': None, 'issues': []}, 'explanation': {'text': 'Unavailable.'}}
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'UNSUPPORTED_EXPLANATION_SOURCE'):
                explanation.explain(state, SimpleNamespace(context=None))
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'UNSUPPORTED_RESPONSE_SOURCE'):
                response.assemble(state)

    def test_compat_turn_clears_previous_presentation(self):
        self.turn(ExplanationScript(actions=actions()))
        model = NativeScript(intent_text='{"task_type":"compat"}', actions=[AIMessage(content='Hello.')])
        result = self.turn(model, request_id='greeting', version=1, text='Hello.')
        self.assertNotIn('type', result)
        self.assertNotIn('allocation', result)
        self.assertEqual(result['assistant_message']['content'], 'Hello.')
        self.assertIsNone(self.checkpoint().values['response'])
        self.assertIsNone(self.checkpoint().values['explanation'])

    def test_main_v1_resumes_respond_then_new_request_uses_main_v2(self):
        interrupted = NativeScript(actions=actions()[:3])
        with patch.object(runtime, 'CURRENT_WORKFLOW', 'main_v1'), \
             patch.object(runtime, 'build_main_graph', side_effect=main_graph.build_v1_graph):
            with self.assertRaises(chat.ChatError):
                self.turn(interrupted)
        self.assertEqual(self.checkpoint().values['workflow_version'], 'main_v1')
        self.assertEqual(self.checkpoint(legacy=True).next, ('respond',))
        recovered = ExplanationScript(actions=[AIMessage(content='Review the saved legacy recommendation.')])
        result = self.turn(recovered)
        self.assertIsNotNone(result['recommendation_id'])
        self.assertFalse(recovered.explanation_prompts)
        self.assertNotIn('allocation', result)
        self.assertEqual(len(self.trace()['tool_calls']), 3)
        greeting = NativeScript(intent_text='{"task_type":"compat"}', actions=[AIMessage(content='Hello.')])
        self.turn(greeting, request_id='new', version=1, text='Hello.')
        self.assertEqual(self.checkpoint().values['workflow_version'], 'main_v2')

    def test_false_commit_claim_is_corrected_in_both_text_fields(self):
        model = ExplanationScript(actions=[*actions()[:3], AIMessage(content='I have committed the recommendation.')])
        result = self.turn(model)
        self.assertEqual(result['explanation'], result['assistant_message']['content'])
        self.assertIn('No allocation was committed', result['explanation'])
        self.assertFalse(result['committed'])
        self.assertIsNotNone(result['allocation'])

    def test_explicit_negative_commit_sentence_keeps_the_explanation(self):
        text = 'Allocation plan: Review the saved plan. No allocation has been committed by this plan.'
        model = ExplanationScript(actions=[*actions()[:3], AIMessage(content=text)])
        result = self.turn(model)
        self.assertEqual(result['explanation'], text)
        self.assertFalse(result['committed'])

    def test_negative_sentence_cannot_hide_a_later_false_commit_claim(self):
        text = 'No allocation has been committed. I have committed the recommendation.'
        model = ExplanationScript(actions=[*actions()[:3], AIMessage(content=text)])
        result = self.turn(model)
        self.assertNotEqual(result['explanation'], text)
        self.assertIn('No allocation was committed', result['explanation'])

    def test_old_response_without_evidence_field_remains_readable(self):
        result = self.turn(ExplanationScript(actions=actions()))
        session = chat.inspect(self.sid, owner='alice', db_path=self.path)
        session['recommendation']['result'].pop('explanation_evidence')
        legacy = {key: deepcopy(result[key]) for key in ('type', 'explanation', 'allocation', 'issues', 'recommendation_id')}
        legacy['allocation'].pop('explanation_evidence')
        reconciled = presentation.reconcile_response(legacy, session)
        self.assertEqual(reconciled['allocation'], legacy['allocation'])
        self.assertEqual(reconciled['explanation'], legacy['explanation'])

    def test_http_serializes_allocation_with_its_explanation(self):
        model = ExplanationScript(actions=actions())
        settings = ModelSettings(default_mode='llm', default_model='native',
            models=(ModelSpec('native', 'openai', 'test-model', 'dummy'),))
        app = create_app(Settings(db_path=self.path, as_of=date(2026, 4, 1), require_auth=False),
                         model_settings=settings, model_factory=lambda spec: model)
        with TestClient(app) as client:
            created = client.post('/api/chat/sessions', json={'request_id': 'http-create', 'mode': 'llm'})
            self.assertEqual(created.status_code, 200)
            sid = created.json()['session_id']
            result = client.post(f'/api/chat/sessions/{sid}/turns', json={
                'request_id': 'http-allocation', 'expected_version': 0, 'message': 'Allocate ORD-045.'})
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body['type'], 'allocation')
        self.assertEqual(body['explanation'], body['assistant_message']['content'])
        self.assertEqual(body['allocation']['order_id'], 'ORD-045')
        self.assertEqual(body['allocation']['recommendation_id'], body['cards'][0]['recommendation_id'])
