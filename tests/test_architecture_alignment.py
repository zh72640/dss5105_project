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
from app.config.model_settings import ModelSpec


class NativeScript:
    def __init__(self, *, order_id="ORD-045", pieces=None, actions=(), sequence=1,
                 intent_text='{"task_type":"allocation"}', provider="openai", output_method="prompt"):
        self.sequence = sequence
        self.intent_text = intent_text
        self.order_id = order_id
        self.pieces = pieces
        self.actions = list(actions)
        self.offered = []
        self.preparation_prompts = []
        self.agent_messages = []
        self.spec = ModelSpec("mock", provider, "mock", "test", output_method=output_method)
        self.structured_bindings = []

    def resolve(self, mode, key):
        return self.spec

    def get_model(self, mode, key):
        return self

    def bind_tools(self, schemas):
        self.offered.append({item["function"]["name"] for item in schemas})
        return self

    def with_structured_output(self, schema, *, method, include_raw):
        self.structured_bindings.append((schema, method, include_raw))
        parent = self

        class Bound:
            def invoke(self, messages):
                import json
                raw = parent.invoke(messages)
                parsed = json.loads(raw.text)
                if hasattr(schema, "model_validate"):
                    parsed = schema.model_validate(parsed)
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return Bound()

    def invoke(self, messages):
        system = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
        if "Classify the current user message" in system:
            return AIMessage(content=self.intent_text)
        if "Extract the user's allocation request" in system:
            return AIMessage(content=self.invoke_task("llm", "mock", _Bundle(messages))[0]["text"])
        self.agent_messages.append(messages)
        return self.actions.pop(0)

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

class _Bundle:
    def __init__(self, messages):
        self._messages = messages
        self.metadata = {"id": "allocation.extract"}

    def as_messages(self):
        return self._messages


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

    def test_each_provider_binds_task_schema_for_current_call(self):
        for provider in ("deepseek", "claude", "openai", "gemini"):
            with self.subTest(provider=provider):
                self.sid = chat.create(owner="alice", request_id="create-" + provider,
                    db_path=self.path, as_of=date(2026, 4, 1), mode="llm")["session_id"]
                model = NativeScript(provider=provider, output_method="json_schema",
                    actions=[call("compute_plan", "plan-" + provider),
                             call("save_recommendation", "save-" + provider),
                             AIMessage(content="Review the saved recommendation.")])
                result = chat.turn(self.sid, owner="alice", request_id="allocate-" + provider,
                    expected_version=0, db_path=self.path, message="Allocate ORD-045.", registry=model)
                self.assertEqual(result["task_state"], "RECOMMENDED")
                self.assertEqual([binding[1] for binding in model.structured_bindings],
                                 ["json_schema", "json_schema"])
                self.assertIsNot(model.structured_bindings[0][0], model.structured_bindings[1][0])

    def test_turn_usage_includes_intent_extract_tool_steps_and_reply(self):
        class Metered(NativeScript):
            def invoke(self, messages):
                response = super().invoke(messages)
                response.usage_metadata = {"input_tokens": 2, "output_tokens": 1,
                                           "total_tokens": 3}
                return response

        model = Metered(actions=[call("compute_plan", "meter-plan"),
                                 call("save_recommendation", "meter-save"),
                                 AIMessage(content="Review the recommendation.")])
        self.turn("Allocate ORD-045.", model)
        with Database(self.path) as db:
            import json
            telemetry = json.loads(db.connection.execute(
                "SELECT telemetry_json FROM chat_turns WHERE request_id='allocate'").fetchone()[0])
            stages = [json.loads(row[0])["stage"] for row in db.connection.execute(
                "SELECT detail_json FROM chat_agent_events WHERE request_id='allocate' AND event_type='model_call'")]
        self.assertEqual(stages, ["intent", "extract", "tool_loop", "tool_loop", "reply"])
        self.assertEqual(telemetry["model_calls"], 5)
        self.assertEqual(telemetry["usage"], {"input_tokens": 10, "output_tokens": 5,
                                               "total_tokens": 15})

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
        from app.llm.errors import BackendError

        class FlakyIntent(NativeScript):
            fail_once = True

            def invoke(self, messages):
                system = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
                if "Classify the current user message" in system and self.fail_once:
                    self.fail_once = False
                    raise BackendError("temporary_failure")
                return super().invoke(messages)

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

