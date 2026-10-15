"""The new LLM Allocation graph uses fixed preparation and guarded completion."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shutil

from langchain_core.messages import AIMessage

from app.db.database import Database
from app.services import chat


class NativeScript:
    def __init__(self, *, order_id="ORD-045", pieces=None, actions=(), sequence=1,
                 intent_text='{"task_type":"allocation"}'):
        self.sequence = sequence
        self.intent_text = intent_text
        self.order_id = order_id
        self.pieces = pieces
        self.actions = list(actions)
        self.offered = []
        self.preparation_prompts = []
        self.agent_messages = []

    def invoke_task(self, mode, key, bundle):
        identifier = bundle.metadata["id"]
        if identifier == "agent.intent":
            return {"text": self.intent_text}, {}
        if identifier != "allocation.extract":
            raise AssertionError(identifier)
        self.preparation_prompts.append(bundle.as_messages())
        message = bundle.as_messages()[-1]["content"]
        patches = []
        if self.order_id:
            patches.append({"op": "set", "field": "order_id", "value": self.order_id,
                            "evidence": {"message_sequence": self.sequence, "quote": message}})
        if self.pieces is not None:
            patches.append({"op": "set", "field": "pieces", "value": self.pieces,
                            "evidence": {"message_sequence": self.sequence, "quote": message}})
        import json
        return {"text": json.dumps({"intent": "allocate_request", "patch_operations": patches})}, {}

    def invoke_tools(self, mode, key, messages, schemas):
        self.offered.append({item["function"]["name"] for item in schemas})
        self.agent_messages.append(messages)
        return self.actions.pop(0)


def call(name, sequence):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": sequence}])


class AlignmentBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "alignment.sqlite3")
        self.sid = chat.create(owner="alice", request_id="create", db_path=self.path,
                               as_of=date(2026, 4, 1), mode="llm")["session_id"]

    def turn(self, text, model):
        return chat.turn(self.sid, owner="alice", request_id="allocate",
                         expected_version=0, db_path=self.path,
                         message=text, registry=model)

    def test_preparation_and_saved_preview(self):
        model = NativeScript(actions=[call("compute_plan", "plan"),
                                      call("save_recommendation", "save"),
                                      AIMessage(content="The recommendation is ready for confirmation.")])
        result = self.turn("Allocate ORD-045.", model)
        self.assertEqual(result["task_state"], "RECOMMENDED")
        self.assertFalse(result["committed"])
        self.assertIsNotNone(result["recommendation_id"])
        self.assertNotIn("record_production_event", model.offered[0])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 0)
            metadata = db.connection.execute(
                "SELECT metadata_json FROM chat_messages WHERE session_id=? AND role='assistant'",
                (self.sid,)).fetchone()[0]
            import json
            self.assertEqual(json.loads(metadata)["workflow"], "main_v1")

    def test_missing_order_blocks_before_tools(self):
        model = NativeScript(order_id=None)
        result = self.turn("Please allocate an order.", model)
        self.assertEqual(result["task_state"], "BLOCKED")
        self.assertFalse(model.offered)
        self.assertIsNone(result["recommendation_id"])

    def test_registered_order_fact_overrides_description(self):
        model = NativeScript(pieces=999, actions=[call("compute_plan", "plan"),
                                                  call("save_recommendation", "save"),
                                                  AIMessage(content="Review the recommendation.")])
        result = self.turn("Allocate ORD-045, 999 pieces.", model)
        self.assertEqual(result["task_state"], "RECOMMENDED")
        differences = result["validation_report"]["resolved_differences"]
        self.assertIn("pieces", {item["field"] for item in differences})
        self.assertEqual(result["session"]["task"]["draft"]["pieces"], 150)

    def test_model_stopping_early_does_not_complete(self):
        model = NativeScript(actions=[AIMessage(content="The recommendation is ready.")])
        result = self.turn("Allocate ORD-045.", model)
        self.assertIsNone(result["recommendation_id"])
        self.assertIn("No verified recommendation", result["assistant_message"]["content"])
    def test_explicit_confirmation_and_replay(self):
        model = NativeScript(actions=[call("compute_plan", "plan"),
                                      call("save_recommendation", "save"),
                                      AIMessage(content="Review the saved recommendation.")])
        preview = self.turn("Allocate ORD-045.", model)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 0)
        confirmed = chat.turn(self.sid, owner="alice", request_id="confirm-1",
            expected_version=1, db_path=self.path, action="confirm",
            recommendation_id=preview["recommendation_id"])
        self.assertTrue(confirmed["committed"])
        replayed = chat.turn(self.sid, owner="alice", request_id="confirm-1",
            expected_version=1, db_path=self.path, action="confirm",
            recommendation_id=preview["recommendation_id"])
        self.assertTrue(replayed["replayed"])
        with Database(self.path) as db:
            self.assertGreater(db.connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM decision_log WHERE order_id='ORD-045'").fetchone()[0], 1)

    def test_invalid_intent_fails_without_tools(self):
        model = NativeScript(intent_text="not JSON")
        result = self.turn("Allocate ORD-045.", model)
        self.assertFalse(model.offered)
        self.assertIn("classified reliably", result["assistant_message"]["content"])

    def test_waiting_skill_snapshot_survives_file_update(self):
        from app.agent import skills
        root = Path(self.temp.name) / "skills"
        root.mkdir()
        source = Path(skills.SKILL_ROOT) / "allocation-recommendation"
        shutil.copytree(source, root / "allocation-recommendation")
        first = NativeScript(actions=[AIMessage(content="", tool_calls=[{
            "name": "ask_user", "args": {"question": "Which objective should I use?"},
            "id": "question"}])])
        with patch.object(skills, "SKILL_ROOT", root):
            waiting = self.turn("Allocate ORD-045.", first)
            self.assertEqual(waiting["pending_question"], "Which objective should I use?")
            skill_path = root / "allocation-recommendation" / "SKILL.md"
            skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nUpdated instructions.\n", encoding="utf-8")
            second = NativeScript(order_id=None, sequence=3, actions=[call("compute_plan", "plan"),
                call("save_recommendation", "save"), AIMessage(content="Review this recommendation.")])
            resumed = chat.turn(self.sid, owner="alice", request_id="resume",
                expected_version=1, db_path=self.path, message="Use the current objective.", registry=second)
        self.assertIsNotNone(resumed["recommendation_id"])
        self.assertNotIn("Updated instructions.", second.agent_messages[0][0].content)
    def test_retry_same_request_after_intent_backend_failure(self):
        from app.core.model_errors import BackendError

        class FlakyIntent(NativeScript):
            fail_once = True

            def invoke_task(self, mode, key, bundle):
                if bundle.metadata["id"] == "agent.intent" and self.fail_once:
                    self.fail_once = False
                    raise BackendError("temporary_failure")
                return super().invoke_task(mode, key, bundle)

        model = FlakyIntent(actions=[call("compute_plan", "plan"),
                                    call("save_recommendation", "save"),
                                    AIMessage(content="Review the recommendation.")])
        with self.assertRaises(chat.ChatError) as failed:
            self.turn("Allocate ORD-045.", model)
        self.assertEqual(failed.exception.code, "MODEL_UNAVAILABLE")
        resumed = self.turn("Allocate ORD-045.", model)
        self.assertIsNotNone(resumed["recommendation_id"])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute(
                "SELECT COUNT(*) FROM chat_agent_runs WHERE request_id='allocate' AND status='finished'").fetchone()[0], 1)
    def test_unsupported_constraint_blocks_before_tools(self):
        import json

        class BudgetRequest(NativeScript):
            def invoke_task(self, mode, key, bundle):
                result, metadata = super().invoke_task(mode, key, bundle)
                if bundle.metadata["id"] == "allocation.extract":
                    payload = json.loads(result["text"])
                    payload["unsupported_constraints"] = ["unsupported_constraint"]
                    result["text"] = json.dumps(payload)
                return result, metadata

        model = BudgetRequest()
        response = self.turn("Allocate ORD-045 with a budget cap.", model)
        self.assertEqual(response["task_state"], "BLOCKED")
        self.assertFalse(model.offered)
        self.assertIsNone(response["recommendation_id"])

    def test_skill_cannot_authorize_production_tool_in_allocation(self):
        model = NativeScript(actions=[AIMessage(content="", tool_calls=[{
            "name": "record_production_event",
            "args": {"action": "cancel", "order_id": "ORD-045", "expected_version": 0,
                     "reason": "planning change"}, "id": "forged-event"}]),
            AIMessage(content="The event was recorded.")])
        response = self.turn("Allocate ORD-045.", model)
        self.assertNotIn("record_production_event", model.offered[0])
        self.assertIsNone(response["recommendation_id"])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM lifecycle_events").fetchone()[0], 0)
            trace = db.connection.execute(
                "SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='record_production_event'").fetchone()
            self.assertIsNotNone(trace)
            import json
            self.assertEqual(json.loads(trace[0])["error"]["code"], "TOOL_NOT_ALLOWED")

