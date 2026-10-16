"""Model error diagnostics and explicit request ending using temporary databases and mocks."""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.main_graph import build_graph
from app.config.model_settings import ModelSettings, ModelSpec
from app.config.settings import Settings
from app.db.database import Database
from app.llm.errors import BackendError, translate_error
from app.main import create_app
from app.services.chat import service as chat
from app.services.chat.request_runs import end_request
from tests.test_allocation_node import actions
from tests.test_architecture_alignment import NativeScript
from tests.test_dynamic_agent import ScriptedNativeModel, tool


class ProviderFailure(Exception):
    def __init__(self, code):
        super().__init__("provider body containing a secret")
        self.code = code


class FailureScript(NativeScript):
    def __init__(self, phase="intent", error=None, **kwargs):
        super().__init__(actions=actions(), **kwargs)
        self.phase = phase
        self.error = error or ProviderFailure(503)

    def invoke(self, messages):
        system = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
        phase = ("intent" if "Classify the current user message" in system else
                 "extract" if "Extract the user's allocation request" in system else
                 "explanation" if "Explain the allocation result" in system else "tool_loop")
        if phase == self.phase and (phase != "tool_loop" or len(self.actions) == 2):
            raise self.error
        return super().invoke(messages)


class ModelFailureClassification(unittest.TestCase):
    def test_status_code_and_gemini_code_and_exception_chain(self):
        for status in (400, 401, 403, 404, 408, 429, 500, 503):
            for wrapped in (False, True):
                with self.subTest(status=status, wrapped=wrapped):
                    source = ProviderFailure(status)
                    if wrapped:
                        wrapper = RuntimeError("secret wrapper text")
                        wrapper.__cause__ = source
                        source = wrapper
                    result = translate_error(source, "gemini")
                    self.assertEqual(str(result), f"gemini_http_{status}")
                    self.assertEqual(result.upstream_status, status)
                    self.assertEqual(result.retryable, status in (408, 429) or status >= 500)
                    self.assertNotIn("secret", json.dumps(result.details()))
                    self.assertNotIn("secret", result.user_message())
                    if wrapped:self.assertEqual(result.cause_types, ["ProviderFailure"])
        source = RuntimeError()
        source.status_code = 429
        self.assertTrue(translate_error(source, "openai").retryable)

    def test_timeout_unknown_and_existing_errors(self):
        error = RuntimeError("private body")
        error.__cause__ = TimeoutError()
        self.assertTrue(translate_error(error, "gemini").retryable)
        self.assertFalse(translate_error(ValueError(), "gemini").retryable)
        known = BackendError("model_refusal", retryable=False)
        self.assertIs(translate_error(known, "gemini"), known)
        cyclic = RuntimeError()
        cyclic.__cause__ = cyclic
        self.assertFalse(translate_error(cyclic, "gemini").retryable)


class RequestEnding(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "requests.sqlite3")
        self.sid = chat.create(owner="alice", request_id="create", db_path=self.path,
            as_of=date(2026, 4, 1), mode="llm")["session_id"]

    def turn(self, model, request_id="failed", version=0, text="Allocate ORD-045."):
        return chat.turn(self.sid, owner="alice", request_id=request_id,
            expected_version=version, message=text, db_path=self.path, registry=model)

    def end(self, request_id="failed", version=0, owner="alice", sid=None):
        return end_request(sid or self.sid, owner=owner, request_id=request_id,
            expected_version=version, db_path=self.path)

    def rows(self, sql):
        with Database(self.path) as db:return [tuple(row) for row in db.connection.execute(sql)]

    def test_end_at_each_model_phase_allows_fresh_request_and_preserves_checkpoints(self):
        for phase in ("intent", "extract", "tool_loop", "explanation"):
            with self.subTest(phase=phase):
                self.sid = chat.create(owner="alice", request_id="create-" + phase,
                    db_path=self.path, as_of=date(2026, 4, 1), mode="llm")["session_id"]
                request_id = "failed-" + phase
                with self.assertRaises(chat.ChatError) as failed:
                    self.turn(FailureScript(phase), request_id)
                details = failed.exception.details
                self.assertEqual(details["phase"], phase)
                self.assertEqual(details["model_error"]["upstream_status"], 503)
                self.assertTrue(details["retryable"])
                old_tools = self.rows("SELECT invocation_key FROM chat_agent_tool_calls")
                old_recs = self.rows("SELECT recommendation_id,status FROM chat_recommendations")
                result = self.end(request_id)
                self.assertTrue(result["ended"])
                self.assertEqual(result["session_version"], 1)
                self.assertEqual(self.rows("SELECT invocation_key FROM chat_agent_tool_calls"), old_tools)
                self.assertEqual(self.rows("SELECT recommendation_id,status FROM chat_recommendations"), old_recs)
                with closing(sqlite3.connect(self.path, check_same_thread=False)) as connection:
                    old = build_graph(SqliteSaver(connection)).get_state({
                        "configurable": {"thread_id": "chat-agent:" + self.sid}})
                self.assertTrue(old.next)
                fresh = self.turn(NativeScript(actions=actions(phase), sequence=3), "new-" + phase, 1)
                self.assertEqual(fresh["session_version"], 2)
                self.assertIsNotNone(fresh["recommendation_id"])
                with self.assertRaises(chat.ChatError) as ended:
                    self.turn(NativeScript(), request_id)
                self.assertEqual(ended.exception.code, "REQUEST_ENDED")

    def test_end_is_idempotent_even_after_later_turn_and_validates_original_version(self):
        with self.assertRaises(chat.ChatError):self.turn(FailureScript())
        first = self.end()
        self.turn(NativeScript(actions=actions(), sequence=3), "new", 1)
        replay = self.end()
        self.assertEqual(replay, {**first, "replayed": True})
        self.assertEqual(chat.inspect(self.sid, owner="alice", db_path=self.path)["version"], 2)
        with self.assertRaises(chat.ChatError) as conflict:self.end(version=1)
        self.assertEqual(conflict.exception.code, "SESSION_VERSION_CONFLICT")
        self.assertEqual(len(self.rows("SELECT * FROM chat_agent_events WHERE event_type='request_ended'")), 1)

    def test_owner_session_and_request_guards(self):
        with self.assertRaises(chat.ChatError):self.turn(FailureScript())
        other = chat.create(owner="alice", request_id="other", db_path=self.path,
            as_of=date(2026, 4, 1), mode="llm")["session_id"]
        for kwargs, code in (({"owner":"bob"}, "SESSION_NOT_FOUND"),
                             ({"sid":other}, "REQUEST_NOT_FOUND"),
                             ({"request_id":"missing"}, "REQUEST_NOT_FOUND")):
            with self.subTest(kwargs=kwargs), self.assertRaises(chat.ChatError) as failed:self.end(**kwargs)
            self.assertEqual(failed.exception.code, code)
        self.assertEqual(self.rows("SELECT status FROM chat_agent_runs"), [("running",)])

    def test_new_request_reports_the_actual_interrupted_request_to_end(self):
        with self.assertRaises(chat.ChatError):self.turn(FailureScript())
        with self.assertRaises(chat.ChatError) as blocked:self.turn(NativeScript(), "new")
        self.assertEqual(blocked.exception.code, "AGENT_RUN_IN_PROGRESS")
        self.assertEqual(blocked.exception.details["request_id"], "failed")
        self.assertFalse(blocked.exception.details["retryable"])
        self.assertTrue(blocked.exception.details["can_end"])
        self.assertEqual(len(self.rows("SELECT * FROM chat_agent_runs")), 1)
        self.assertTrue(self.end()["ended"])

    def test_completed_request_is_not_ended_and_recommendation_is_unchanged(self):
        result = self.turn(NativeScript(actions=actions()))
        before = self.rows("SELECT * FROM chat_recommendations")
        ended = self.end()
        self.assertFalse(ended["ended"])
        self.assertEqual(ended["session_version"], result["session_version"])
        self.assertEqual(self.rows("SELECT * FROM chat_recommendations"), before)
        self.assertFalse(self.rows("SELECT * FROM chat_agent_events WHERE event_type='request_ended'"))

    def test_nonretryable_error_retains_request_until_explicit_end(self):
        with self.assertRaises(chat.ChatError) as failed:
            self.turn(FailureScript(error=ProviderFailure(401)))
        self.assertEqual(failed.exception.code, "MODEL_REQUEST_FAILED")
        self.assertFalse(failed.exception.details["retryable"])
        self.assertTrue(failed.exception.details["can_end"])
        self.assertIn("authentication", str(failed.exception))
        self.assertEqual(self.rows("SELECT status FROM chat_agent_runs"), [("running",)])
        self.assertTrue(self.end()["ended"])

    def test_end_during_model_execution_is_rejected_and_claim_is_released_after_error(self):
        started, release = Event(), Event()
        outcome = []
        class SlowScript(FailureScript):
            def invoke(self, messages):
                started.set()
                if not release.wait(10):raise AssertionError("release timed out")
                return super().invoke(messages)
        def execute():
            try:self.turn(SlowScript())
            except Exception as error:outcome.append(error)
        thread = Thread(target=execute)
        thread.start()
        self.addCleanup(lambda: (release.set(), thread.join(10)))
        self.assertTrue(started.wait(10))
        with self.assertRaises(chat.ChatError) as active:self.end()
        self.assertEqual(active.exception.code, "REQUEST_EXECUTING")
        self.assertFalse(self.rows("SELECT * FROM chat_agent_events WHERE event_type='request_ended'"))
        release.set();thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcome[0], chat.ChatError)
        self.assertTrue(self.end()["ended"])

    def test_ending_after_production_write_preserves_event_and_prevents_reexecution(self):
        result = self.turn(NativeScript(actions=actions()), "plan")
        rec = result["session"]["recommendation"]
        chat.turn(self.sid, owner="alice", request_id="confirm", expected_version=1,
            action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)
        wid = rec["result"]["allocation"][0]["workshop_id"]
        version = self.rows("SELECT version FROM orders WHERE order_id='ORD-045'")[0][0]
        text = f"Complete 1 piece for ORD-045 at {wid} because inspection passed."
        model = ScriptedNativeModel(tool("load_skill", name="commit-and-production"),
            tool("record_production_event", action="complete", order_id="ORD-045",
                expected_version=version, reason="inspection passed", workshop_id=wid, pieces=1))
        with self.assertRaises(chat.ChatError):self.turn(model, "production", 2, text)
        before = self.rows("SELECT * FROM lifecycle_events")
        self.assertTrue(before)
        self.end("production", 2)
        self.assertEqual(self.rows("SELECT * FROM lifecycle_events"), before)
        with self.assertRaises(chat.ChatError) as ended:self.turn(model, "production", 2, text)
        self.assertEqual(ended.exception.code, "REQUEST_ENDED")
        fresh = ScriptedNativeModel(AIMessage(content="The earlier event is saved."))
        self.turn(fresh, "query", 3, "What happened in this session?")
        self.assertEqual(self.rows("SELECT * FROM lifecycle_events"), before)

    def test_http_error_details_and_end_with_initial_message(self):
        model = FailureScript(provider="gemini")
        settings = ModelSettings(default_mode="llm", default_model="mock", models=(
            ModelSpec("mock", "gemini", "test-model", "dummy"),))
        app = create_app(Settings(db_path=self.path, require_auth=False),
            model_settings=settings, model_factory=lambda spec:model)
        with TestClient(app) as client:
            failed = client.post("/api/chat/sessions", json={"request_id":"http-create",
                "mode":"llm", "message":"Allocate ORD-045."})
            self.assertEqual(failed.status_code, 503)
            body = failed.json()
            details = body["details"]
            self.assertEqual(body["error"], "MODEL_UNAVAILABLE")
            self.assertEqual(details["model_error"]["upstream_status"], 503)
            self.assertNotIn("secret", failed.text)
            url = f"/api/chat/sessions/{details['session_id']}/requests/{details['request_id']}/end"
            ended = client.post(url, json={"expected_version":details["expected_version"]})
            self.assertEqual(ended.status_code, 200)
            self.assertTrue(ended.json()["ended"])
            replay = client.post(url, json={"expected_version":details["expected_version"]})
            self.assertTrue(replay.json()["replayed"])
            self.assertEqual(client.post(url, json={"expected_version":"0"}).status_code, 400)
