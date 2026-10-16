"""Basic allocation contracts, guarded execution and downstream response recovery.

All model calls are scripted and all database changes use temporary fixtures.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent import allocation_graph, dynamic, skills
from app.agent.main_graph import build_graph
from app.agent.executor import run as run_executor
from app.db.database import Database
from app.db import agent_repository
from app.llm.errors import BackendError
from app.services.allocation.contracts import FIELDS, add_order_snapshot, inspect_input, saved_result
from app.services.chat import operations, service as chat
from app.services.chat.completion import BASIC_ALLOCATION_POLICY, evaluate_allocation
from tests.test_architecture_alignment import NativeScript, call


def actions(suffix=""):
    return [call("check_requirements", "check" + suffix), call("compute_plan", "compute" + suffix),
            call("save_recommendation", "save" + suffix), AIMessage(content="Review the saved recommendation.")]


class ExtractionScript(NativeScript):
    def __init__(self, patches=(), *, malformed=None, failure=None, **kwargs):
        super().__init__(**kwargs)
        self.patches = patches
        self.malformed = malformed
        self.failure = failure

    def invoke_task(self, mode, key, bundle):
        if self.failure:
            raise self.failure
        if self.malformed is not None:
            return {"text": self.malformed}, {}
        result, metadata = super().invoke_task(mode, key, bundle)
        value = json.loads(result["text"])
        for field, item in self.patches:
            value["patch_operations"].append({"op": "set", "field": field, "value": item,
                "quote": bundle.as_messages()[-1]["content"]})
        result["text"] = json.dumps(value)
        return result, metadata


class AllocationNodeBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "allocation.sqlite3")
        self.sid = chat.create(owner="alice", request_id="create", db_path=self.path,
                               as_of=date(2026, 4, 1), mode="llm")["session_id"]

    def turn(self, model, text="Allocate ORD-045."):
        return chat.turn(self.sid, owner="alice", request_id="allocation", expected_version=0,
                         db_path=self.path, message=text, registry=model)

    def checkpoint(self):
        with closing(sqlite3.connect(self.path, check_same_thread=False)) as connection:
            return build_graph(SqliteSaver(connection)).get_state(
                {"configurable": {"thread_id": "chat-agent:" + self.sid}}).values

    def calls(self):
        return chat.execution_trace(self.sid, owner="alice", db_path=self.path)["tool_calls"]

    def test_id_only_enriches_and_returns_saved_snapshot_before_response(self):
        class Capture(NativeScript):
            def invoke(self, messages):
                system = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
                if "Explain the allocation result" in system:
                    with Database(self_path) as db:
                        self.saved_before_response = db.connection.execute(
                            "SELECT COUNT(*) FROM chat_recommendations").fetchone()[0]
                    self.response_prompt = messages[-1]["content"] if isinstance(messages[-1], dict) else messages[-1].content
                    self.binding_count = len(self.offered)
                return super().invoke(messages)
        self_path = self.path
        model = Capture(actions=actions())
        response = self.turn(model)
        payload = self.checkpoint()["task_result"]["result"]
        rec = response["session"]["recommendation"]
        self.assertEqual(payload, saved_result(rec))
        self.assertEqual(payload["order_id"], "ORD-045")
        self.assertEqual(payload["pieces"], 150)
        self.assertEqual(payload["allocated_pieces"], 150)
        self.assertTrue(all(payload[field] is not None for field in FIELDS))
        self.assertEqual(payload["delay_days"], (date.fromisoformat(payload["estimated_delivery_date"]) -
                                                date.fromisoformat(payload["due_date"])).days)
        self.assertEqual([item["tool_name"] for item in self.calls()],
                         ["check_requirements", "compute_plan", "save_recommendation"])
        self.assertEqual(model.saved_before_response, 1)
        self.assertEqual(model.binding_count, 3)
        self.assertTrue(all(offered == {"check_requirements", "compute_plan", "save_recommendation"}
                            for offered in model.offered))
        self.assertIn(payload["recommendation_id"], model.response_prompt)
        self.assertIn('Prepared skill_input:', model.agent_messages[0][0].content)
        self.assertFalse(response["committed"])

    def test_invalid_extracted_quantity_stops_before_preparation(self):
        model = ExtractionScript(pieces="150", actions=actions())
        response = self.turn(model, "Allocate ORD-045, 150 pieces.")
        self.assertEqual(self.checkpoint()["task_result"]["issues"][0]["code"], "EXTRACTION_FORMAT_INVALID")
        self.assertIn("format validation failed", response["assistant_message"]["content"])
        self.assertFalse(model.offered)
        self.assertIsNone(response["recommendation_id"])
        self.assertEqual(response["session"]["task"]["task_version"], 0)

    def test_malformed_json_is_format_failure(self):
        response = self.turn(ExtractionScript(malformed="not json"))
        self.assertIn("format validation failed", response["assistant_message"]["content"])

    def test_structured_parse_failure_is_format_failure(self):
        class InvalidStructured(ExtractionScript):
            def with_structured_output(self, schema, **kwargs):
                if not hasattr(schema, "model_validate"):
                    return super().with_structured_output(schema, **kwargs)
                return SimpleNamespace(invoke=lambda messages: {
                    "raw": AIMessage(content="invalid"), "parsed": None,
                    "parsing_error": ValueError("invalid fields")})
        model = InvalidStructured(output_method="json_schema")
        self.turn(model)
        self.assertEqual(self.checkpoint()["task_result"]["issues"][0]["code"], "EXTRACTION_FORMAT_INVALID")
        self.assertFalse(model.offered)

    def test_provider_failure_remains_retryable_and_does_not_become_missing_data(self):
        model = ExtractionScript(failure=BackendError("temporary_failure"), actions=actions())
        with self.assertRaises(chat.ChatError) as failed:
            self.turn(model)
        self.assertEqual(failed.exception.code, "MODEL_UNAVAILABLE")
        self.assertFalse(model.offered)
        model.failure = None
        self.assertIsNotNone(self.turn(model)["recommendation_id"])

    def test_missing_fields_are_reported_without_follow_up_tools(self):
        model = NativeScript(order_id=None)
        response = self.turn(model, "Allocate an order.")
        result = self.checkpoint()["task_result"]
        self.assertEqual(result["status"], "blocked")
        missing = [item for item in result["issues"] if item["code"] == "REQUIRED_INFO_INCOMPLETE"]
        self.assertEqual({item["field"] for item in missing}, set(FIELDS))
        self.assertIsNone(response["pending_question"])
        self.assertFalse(model.offered)

    def test_database_facts_override_product_quantity_and_deadline(self):
        model = ExtractionScript(patches=[("product", "Other shirt"), ("due_date", "2027-01-01")],
                                 pieces=999, actions=actions())
        response = self.turn(model, "Allocate ORD-045: Other shirt, 999 pieces, due 2027-01-01.")
        payload = self.checkpoint()["task_result"]["result"]
        self.assertEqual(payload["pieces"], 150)
        self.assertNotEqual(payload["product"], "Other shirt")
        self.assertNotEqual(payload["due_date"], "2027-01-01")
        self.assertEqual({item["field"] for item in response["validation_report"]["resolved_differences"]},
                         {"product", "pieces", "due_date"})

    def test_explicit_multiple_workshops_stop_before_skill(self):
        model = ExtractionScript(patches=[("num_workshop_allowed", 2)])
        self.turn(model, "Allocate ORD-045 using at most two workshops.")
        self.assertEqual(self.checkpoint()["task_result"]["issues"][0]["code"], "MULTI_WORKSHOP_UNSUPPORTED")
        self.assertFalse(model.offered)

    def test_missing_registered_due_date_is_a_missing_field(self):
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE orders SET due_date='' WHERE order_id='ORD-045'")
        model = NativeScript()
        self.turn(model)
        issues = self.checkpoint()["task_result"]["issues"]
        self.assertEqual(issues[0]["code"], "REQUIRED_INFO_INCOMPLETE")
        self.assertEqual(issues[0]["missing_fields"], ["due_date"])
        self.assertFalse(model.offered)

    def test_unproven_extraction_is_rejected_before_database_enrichment(self):
        model = NativeScript(order_id="ORD-046")
        self.turn(model)
        self.assertEqual(self.checkpoint()["task_result"]["issues"][0]["code"], "EXTRACTION_EVIDENCE_INVALID")
        self.assertFalse(model.offered)

    def test_remaining_quantity_is_computed_but_order_total_is_returned(self):
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE orders SET completed_pieces=50 WHERE order_id='ORD-045'")
        self.turn(NativeScript(actions=actions()))
        payload = self.checkpoint()["task_result"]["result"]
        self.assertEqual(payload["pieces"], 150)
        self.assertEqual(payload["allocated_pieces"], 100)

    def test_basic_workflow_cannot_ask_a_follow_up_question(self):
        model = NativeScript(actions=[AIMessage(content="", tool_calls=[{
            "name": "ask_user", "args": {"question": "Which objective should I use?"}, "id": "ask"}])])
        response = self.turn(model)
        self.assertIsNone(response["pending_question"])
        self.assertEqual(self.calls()[0]["result"]["error"]["code"], "TOOL_NOT_ALLOWED")

    def test_out_of_order_batch_stops_all_later_calls(self):
        batch = AIMessage(content="", tool_calls=[
            {"name": name, "args": {}, "id": str(index)}
            for index, name in enumerate(("compute_plan", "check_requirements", "save_recommendation"))])
        response = self.turn(NativeScript(actions=[batch]))
        calls = self.calls()
        self.assertEqual([item["result"]["error"]["code"] for item in calls],
                         ["INVALID_TOOL_SEQUENCE", "TASK_EXECUTION_FINISHED", "TASK_EXECUTION_FINISHED"])
        self.assertIsNone(response["recommendation_id"])

    def test_successful_batch_ends_after_save_without_executing_extra_call(self):
        batch = AIMessage(content="", tool_calls=[
            {"name": name, "args": {}, "id": str(index)} for index, name in enumerate(
                ("check_requirements", "compute_plan", "save_recommendation", "compute_plan"))])
        response = self.turn(NativeScript(actions=[batch, AIMessage(content="Review the saved recommendation.")]))
        self.assertIsNotNone(response["recommendation_id"])
        self.assertEqual(self.calls()[-1]["result"]["error"]["code"], "TASK_EXECUTION_FINISHED")
        self.assertEqual(self.checkpoint()["task_result"]["status"], "waiting_user")

    def test_skill_input_is_rechecked_at_first_tool(self):
        original = allocation_graph.execute_allocation
        def missing(state, runtime):
            state = {**state, "skill_input": {**state["skill_input"], "due_date": None}}
            return original(state, runtime)
        with patch.object(allocation_graph, "execute_allocation", missing):
            response = self.turn(NativeScript(actions=actions()))
        self.assertIn("due_date", response["assistant_message"]["content"])
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0]["result"]["error"]["code"], "SKILL_INPUT_INCOMPLETE")
        self.assertIsNone(response["recommendation_id"])

    def test_no_feasible_workshop_stops_after_compute(self):
        model = NativeScript(actions=actions())
        # No workshop in this temporary fixture can accept the registered batch.
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE workshops SET max_batch_pieces=100")
        response = self.turn(model)
        self.assertIsNone(response["recommendation_id"])
        self.assertEqual(self.calls()[-1]["result"]["error"]["code"], "PLAN_BLOCKED")
        self.assertEqual([item["tool_name"] for item in self.calls()], ["check_requirements", "compute_plan"])

    def test_one_stale_plan_retries_from_requirements_then_saves_once(self):
        original = operations.save_recommendation
        saves = 0
        def stale_once(connection, session, as_of, plan, **kwargs):
            nonlocal saves
            saves += 1
            if saves == 1:
                operations.block_plan(connection, session, session["task"]["report"], "STALE_PLAN", "Facts changed.")
            return original(connection, session, as_of, plan, **kwargs)
        with patch.object(operations, "save_recommendation", stale_once):
            response = self.turn(NativeScript(actions=[*actions()[:3], *actions("-retry")]))
        self.assertIsNotNone(response["recommendation_id"])
        self.assertEqual([item["tool_name"] for item in self.calls()],
                         ["check_requirements", "compute_plan", "save_recommendation"] * 2)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM chat_recommendations").fetchone()[0], 1)

    def test_second_stale_plan_stops(self):
        def stale(connection, session, as_of, plan, **kwargs):
            operations.block_plan(connection, session, session["task"]["report"], "STALE_PLAN", "Facts changed.")
        with patch.object(operations, "save_recommendation", stale):
            response = self.turn(NativeScript(actions=[*actions()[:3], *actions("-retry")[:3]]))
        self.assertIsNone(response["recommendation_id"])
        self.assertEqual(self.checkpoint()["task_result"]["issues"][0]["code"], "STALE_PLAN")

    def test_response_failure_resumes_without_extracting_or_saving_again(self):
        model = NativeScript(actions=actions()[:3])
        with self.assertRaises(chat.ChatError):
            self.turn(model)
        self.assertEqual(self.checkpoint()["task_result"]["status"], "waiting_user")
        model.actions = [AIMessage(content="Review the saved recommendation.")]
        response = self.turn(model)
        self.assertIsNotNone(response["recommendation_id"])
        self.assertEqual(len(model.preparation_prompts), 1)
        self.assertEqual(len(self.calls()), 3)
        replay = self.turn(NativeScript())
        self.assertTrue(replay["replayed"])

    def test_response_cannot_execute_a_business_tool(self):
        model = NativeScript(actions=[*actions()[:3], AIMessage(content="", tool_calls=[{
            "name": "compute_plan", "args": {}, "id": "response-tool"}])])
        with self.assertRaises(chat.ChatError) as failed:
            self.turn(model)
        self.assertEqual(failed.exception.code, "MODEL_REQUEST_FAILED")
        self.assertEqual(len(self.calls()), 3)
        model.actions = [AIMessage(content="Review this saved recommendation.")]
        self.assertIsNotNone(self.turn(model)["recommendation_id"])

    def test_legacy_waiting_executor_keeps_its_skill_snapshot_and_policy(self):
        legacy = {**skills.load("allocation-recommendation"), "content": "Pinned legacy instructions.",
                  "tools": ["check_requirements", "compute_plan", "save_recommendation", "ask_user"],
                  "hash": "0" * 64}
        with Database(self.path) as db, db.transaction() as connection:
            agent_repository.start_run(connection, "legacy-wait", self.sid, "legacy", 0)
        model = NativeScript(actions=[AIMessage(content="", tool_calls=[{
            "name": "ask_user", "args": {"question": "Which order should I allocate?"}, "id": "legacy-question"}])])
        context = dynamic.AgentContext(model, None, "alice", self.path, self.sid, "legacy-wait",
            "Allocate an order.", date(2026, 4, 1), skill_root=skills.SKILL_ROOT)
        waiting = run_executor(context, task_type="allocation", loaded_skills={legacy["name"]: legacy})
        self.assertIsNotNone(waiting["pending_question"])
        with Database(self.path) as db, db.transaction() as connection:
            agent_repository.set_run_status(connection, "legacy-wait", "finished")
        resumed = NativeScript(actions=[*actions(), AIMessage(content="Review the saved recommendation.")])
        response = self.turn(resumed)
        self.assertIsNotNone(response["recommendation_id"])
        self.assertIn("Pinned legacy instructions.", resumed.agent_messages[0][0].content)
        self.assertIn("ask_user", resumed.offered[0])
        with closing(sqlite3.connect(self.path, check_same_thread=False)) as connection:
            restored = dynamic.build_graph(SqliteSaver(connection)).get_state({
                "configurable": {"thread_id": "agent-executor:allocation:" + self.sid}}).values
        self.assertIsNone(restored["execution_policy"])
        self.assertEqual(restored["loaded_skills"][legacy["name"]]["hash"], legacy["hash"])

    def test_business_node_returns_data_without_response(self):
        with Database(self.path) as db, db.transaction() as connection:
            agent_repository.start_run(connection, "direct", self.sid, "direct", 0)
        context = dynamic.AgentContext(NativeScript(actions=actions()[:3]), None, "alice", self.path,
            self.sid, "direct", "Allocate ORD-045.", date(2026, 4, 1), skill_root=skills.SKILL_ROOT)
        output = allocation_graph.build_graph().invoke({"messages": []}, context=context)
        self.assertNotIn("reply", output)
        self.assertIn("workshop_id", output["task_result"]["result"])


class AllocationContractBehavior(unittest.TestCase):
    def test_each_required_field_has_an_explicit_missing_issue(self):
        complete = {"order_id": "ORD-045", "product": "Shirt", "pieces": 150, "due_date": "2026-04-03"}
        for field in FIELDS:
            for skill in (False, True):
                with self.subTest(field=field, skill=skill):
                    supplied = {key: value for key, value in complete.items() if key != field}
                    result, issues = inspect_input(supplied, skill=skill)
                    self.assertIsNone(result)
                    self.assertEqual(issues[0]["missing_fields"], [field])
                    self.assertIn(field, issues[0]["question"])

    def test_signed_delay_and_registered_total_are_independent_of_allocated_quantity(self):
        order = {"order_id": "ORD-045", "product": "Shirt", "pieces": 150, "due_date": "2026-04-03"}
        for days in (-2, 0, 3):
            with self.subTest(days=days):
                plan = {"success": True, "allocation": [{"workshop_id": "W1", "workshop_name": "One",
                    "pieces": 100, "defect_rate": .02, "estimated_cost": 500.0}],
                    "estimated_delivery_date": (date(2026, 4, 3) + timedelta(days=days)).isoformat(),
                    "expected_defect_rate": .02, "estimated_cost": 500.0, "objective": "min_delay", "warnings": []}
                enriched = add_order_snapshot(order, plan)
                rec = {"recommendation_id": "rec", "task_version": 1, "result": enriched}
                result = saved_result(rec)
                self.assertEqual(result["delay_days"], days)
                self.assertEqual(result["pieces"], 150)
                self.assertEqual(result["allocated_pieces"], 100)
                self.assertEqual(result["expected_defect_rate"], .02)
                self.assertEqual(result["estimated_cost"], 500.0)
                corrupt = deepcopy(rec)
                corrupt["result"]["delay_days"] += 1
                with self.assertRaises(ValueError):
                    saved_result(corrupt)

    def test_completion_guard_rejects_save_without_mandatory_prior_tools(self):
        result = evaluate_allocation({"task": {"task_id": "task"}, "recommendation": {}},
            [{"name": "save_recommendation", "result": {"ok": True, "data": {}}}],
            execution_policy=BASIC_ALLOCATION_POLICY)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["issues"][0]["code"], "INVALID_TOOL_SEQUENCE")
