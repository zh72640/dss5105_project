"""Behavioral checks for the live Skill/tool graph and transactional guards."""
from datetime import date
from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent import dynamic, skills
from app.agent.dynamic import LOAD_SKILL
from app.services import scoring as original_scores
from app.db.database import Database
from app.core.models.registry import ModelRegistry
from app.core.models.factory import build_model
from app.core.models.specs import ModelSettings, ModelSpec
from app.config.settings import Settings
from app.main import create_app
from app.services import chat
from app.services import lifecycle


def tool(tool_name, **args):
    tool.counter += 1
    return AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": f"call-{tool.counter}"}])


tool.counter = 0


class ScriptedNativeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.offered = []
        self.prompts = []

    def invoke_tools(self, mode, key, messages, schemas):
        self.offered.append({item["function"]["name"] for item in schemas})
        self.prompts.append(messages[0].content)
        return self.responses.pop(0)


class DynamicAgentBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "agent.sqlite3")
        self.sid = chat.create(owner="alice", request_id="create", db_path=self.path,
                               as_of=date(2026, 4, 1), mode="llm")["session_id"]

    def run_turn(self, message, model, request_id, version=0):
        return chat.turn(self.sid, owner="alice", request_id=request_id, expected_version=version,
                         message=message, db_path=self.path, registry=model)

    def rows(self, query):
        with Database(self.path) as db:
            return [tuple(row) for row in db.connection.execute(query)]

    def test_order_query_loads_skill_and_only_uses_query(self):
        model = ScriptedNativeModel(tool("load_skill", name="order-inquiry"),
                                    tool("get_order", order_id="ORD-045"),
                                    AIMessage(content="Order ORD-045 is READY."))
        response = self.run_turn("What is the status of ORD-045?", model, "query")
        self.assertEqual(response["task_state"], "COLLECTING")
        self.assertEqual([x[0] for x in self.rows("SELECT tool_name FROM chat_agent_tool_calls ORDER BY rowid")],
                         ["load_skill", "get_order"])
        self.assertEqual(model.offered[0], {"load_skill"})
        self.assertEqual(model.offered[1], {"load_skill", "get_order", "ask_user"})
        trace = chat.execution_trace(self.sid, owner="alice", db_path=self.path)
        self.assertEqual([item["tool_name"] for item in trace["tool_calls"]], ["load_skill", "get_order"])
        self.assertEqual(trace["tool_calls"][0]["skill_name"], "order-inquiry")
        with self.assertRaises(chat.ChatError):
            chat.execution_trace(self.sid, owner="bob", db_path=self.path)
        self.assertFalse(self.rows("SELECT * FROM working_order"))

    def test_authenticated_http_chat_turn_uses_native_tool_graph_and_trace(self):
        responses = [AIMessage(content='{"task_type":"compat"}'),
                     tool("load_skill", name="order-inquiry"),
                     tool("get_order", order_id="ORD-045"),
                     AIMessage(content="ORD-045 is ready for allocation.")]
        offered = []
        class NativeTransport:
            def bind_tools(self, definitions):
                offered.append({item["function"]["name"] for item in definitions})
                return self
            def invoke(self, messages):
                return responses.pop(0)
        settings = ModelSettings(default_mode="llm", default_model="native",
            models=(ModelSpec("native", "openai", "test-model", "dummy"),))
        app = create_app(Settings(db_path=self.path, require_auth=False),
                         model_settings=settings, model_factory=lambda spec: NativeTransport())
        with TestClient(app) as client:
            created = client.post("/api/chat/sessions", json={"request_id": "http-create", "mode": "llm"})
            self.assertEqual(created.status_code, 200)
            sid = created.json()["session_id"]
            answer = client.post(f"/api/chat/sessions/{sid}/turns", json={
                "request_id": "http-query", "expected_version": 0, "action": "message",
                "message": "What is the status of ORD-045?"})
            self.assertEqual(answer.status_code, 200)
            self.assertIn("ready", answer.json()["assistant_message"]["content"])
            trace = client.get(f"/api/chat/sessions/{sid}/trace")
            self.assertEqual(trace.status_code, 200)
            self.assertEqual([item["tool_name"] for item in trace.json()["tool_calls"]],
                             ["load_skill", "get_order"])
        self.assertEqual(offered[0], {"load_skill"})
        self.assertEqual(offered[1], {"load_skill", "get_order", "ask_user"})

    def test_recommendation_scores_and_commits_once(self):
        model = ScriptedNativeModel(
            tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("score_workshop", workshop_id="W1", order_id="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="The recommendation is ready for explicit confirmation."))
        with patch.object(original_scores, "get_estimated_completion_time", wraps=original_scores.get_estimated_completion_time) as eta, \
             patch.object(original_scores, "get_lateness_score", wraps=original_scores.get_lateness_score) as late, \
             patch.object(original_scores, "get_defect_score", wraps=original_scores.get_defect_score) as defect, \
             patch.object(original_scores, "get_hybrid_score", wraps=original_scores.get_hybrid_score) as hybrid:
            response = self.run_turn("Allocate ORD-045; compare W1 first.", model, "allocate")
        for original in (eta, late, defect, hybrid):
            self.assertGreater(original.call_count, 0)
        self.assertEqual(response["task_state"], "RECOMMENDED")
        self.assertFalse(response["committed"])
        self.assertFalse(self.rows("SELECT * FROM working_order"))
        scores = self.rows("SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='score_workshop'")
        self.assertEqual(len(scores), 1)
        data = json.loads(scores[0][0])["data"]
        resource = self.rows("SELECT capacity_pieces_per_day,pickup_lead_days,defect_rate FROM workshops WHERE workshop_id='W1'")[0]
        self.assertAlmostEqual(data["estimated_completion_days"],
                               data["queue_days"] + data["pieces"] / resource[0] + resource[1])
        self.assertAlmostEqual(data["defect_score"], resource[2])
        due_date = date.fromisoformat(self.rows("SELECT due_date FROM orders WHERE order_id='ORD-045'")[0][0])
        expected_lateness = data["estimated_completion_days"] - (due_date - date.fromisoformat(data["sent_date"])).days
        self.assertAlmostEqual(data["lateness_score_days"], expected_lateness)
        self.assertEqual(data["original_hybrid_score"],
                         data["defect_score"] if expected_lateness <= 0 else 10000)
        rec = response["session"]["recommendation"]
        confirmed = chat.turn(self.sid, owner="alice", request_id="confirm", expected_version=1,
                              action="confirm", recommendation_id=rec["recommendation_id"],
                              db_path=self.path)
        self.assertTrue(confirmed["committed"])
        first_count = len(self.rows("SELECT * FROM working_order"))
        replay = chat.turn(self.sid, owner="alice", request_id="confirm", expected_version=1,
                           action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.rows("SELECT * FROM working_order")), first_count)
        events = chat.execution_trace(self.sid, owner="alice", db_path=self.path)["events"]
        confirmation = [item for item in events if item["event_type"] == "confirmation_committed"]
        self.assertEqual(len(confirmation), 1)
        self.assertEqual(confirmation[0]["detail"]["recommendation_id"], rec["recommendation_id"])
        self.assertEqual(confirmation[0]["detail"]["state_before"], "RECOMMENDED")
        self.assertEqual(confirmation[0]["detail"]["state_after"], "CONFIRMED")

    def test_inactive_workshop_uses_original_score_sentinels(self):
        status = self.rows("SELECT status FROM workshops WHERE workshop_id='W7'")[0][0]
        self.assertNotEqual(status, "ACTIVE")
        model = ScriptedNativeModel(tool("load_skill", name="workshop-inquiry"),
            tool("score_workshop", workshop_id="W7", order_id="ORD-045"),
            AIMessage(content="W7 is not eligible for this allocation."))
        self.run_turn("Compare W7 for ORD-045.", model, "inactive-score")
        data = json.loads(self.rows("SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='score_workshop'")[0][0])["data"]
        self.assertEqual(data["lateness_score_days"], 10000)
        self.assertEqual(data["defect_score"], 10000)
        self.assertEqual(data["original_hybrid_score"], 10000)
        self.assertIsNotNone(data["eligibility_rejection"])

    def test_illegal_save_is_rejected_and_model_can_ask(self):
        model = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
                                    tool("save_recommendation"),
                                    tool("ask_user", question="Which order should I allocate?"))
        response = self.run_turn("Please allocate an order.", model, "missing")
        self.assertEqual(response["pending_question"], "Which order should I allocate?")
        self.assertFalse(self.rows("SELECT * FROM chat_recommendations"))
        self.assertIn("INVALID_TASK_STATE", self.rows("SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='save_recommendation'")[0][0])

    def test_agent_question_and_final_reply_are_english(self):
        question = ScriptedNativeModel(tool("load_skill", name="order-inquiry"),
            tool("ask_user", question="请提供订单号。"),
            tool("ask_user", question="Which order ID should I check?"))
        first = self.run_turn("Check an order for me.", question, "english-question")
        self.assertEqual(first["pending_question"], "Which order ID should I check?")
        self.assertIn("ENGLISH_REQUIRED", self.rows(
            "SELECT result_json FROM chat_agent_tool_calls WHERE request_id='english-question' AND tool_name='ask_user' ORDER BY rowid")[0][0])
        final = ScriptedNativeModel(AIMessage(content="订单已找到。"))
        second = self.run_turn("ORD-045", final, "english-reply", 1)
        self.assertEqual(second["assistant_message"]["content"], "Please continue in English in this session.")

    def test_skill_catalog_is_runtime_loaded(self):
        catalog = skills.catalog()
        self.assertIn("allocation-recommendation", {item["name"] for item in catalog})
        current = skills.load("allocation-recommendation")
        self.assertIn("compute_plan", current["content"])
        self.assertEqual(len(current["hash"]), 64)

    def test_model_registry_uses_native_bind_tools(self):
        calls = []
        class NativeModel:
            def bind_tools(self, definitions):
                calls.append([item["function"]["name"] for item in definitions])
                return self
            def invoke(self, messages):
                calls.append(messages)
                return tool("load_skill", name="order-inquiry")
        settings = ModelSettings(default_mode="llm", default_model="native",
            models=(ModelSpec("native", "openai", "test-model", "dummy"),))
        registry = ModelRegistry(settings, factory=lambda spec: NativeModel())
        registry.initialize()
        result = registry.invoke_tools("llm", "native", [], [LOAD_SKILL])
        self.assertEqual(result.tool_calls[0]["name"], "load_skill")
        self.assertEqual(calls[0], ["load_skill"])

    def test_configured_provider_adapters_accept_native_tool_schemas(self):
        for provider, model_id in (("openai", "gpt-4o-mini"),
                                   ("claude", "claude-sonnet-4-5"),
                                   ("gemini", "gemini-2.5-flash"),
                                   ("deepseek", "deepseek-chat")):
            with self.subTest(provider=provider):
                model = build_model(ModelSpec(provider, provider, model_id, "dummy", output_method="prompt"))
                self.assertIsNotNone(model.bind_tools([LOAD_SKILL]))

    def test_skill_reload_changes_prompt_without_python_or_guard_change(self):
        root = Path(self.temp.name) / "skills"
        shutil.copytree(skills.SKILL_ROOT, root)
        first = ScriptedNativeModel(tool("load_skill", name="order-inquiry"), AIMessage(content="Ready."))
        with patch.object(skills, "SKILL_ROOT", root):
            self.run_turn("I have an order question.", first, "skill-first")
            source = root / "order-inquiry" / "SKILL.md"
            revised = source.read_text(encoding="utf-8").replace("tools: [get_order, ask_user]", "tools: [get_order, ask_user, list_workshops]")
            source.write_text(revised + "\nIf the user requests workshop context, list workshops before answering.\n", encoding="utf-8")
            second = ScriptedNativeModel(tool("load_skill", name="order-inquiry"),
                tool("list_workshops"), AIMessage(content="Workshop details are available."))
            response = self.run_turn("Continue the order question and compare workshops.", second, "skill-second", 1)
        rows = self.rows("SELECT skill_hash,result_json FROM chat_agent_tool_calls WHERE tool_name='load_skill' ORDER BY rowid")
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertIn("list workshops before answering", second.prompts[-1])
        self.assertNotIn("list_workshops", first.offered[-1])
        self.assertIn("list_workshops", second.offered[-1])
        self.assertEqual(response["assistant_message"]["content"], "Workshop details are available.")

    def test_completed_turn_drops_old_skill_permissions(self):
        root = Path(self.temp.name) / "skills"
        shutil.copytree(skills.SKILL_ROOT, root)
        with patch.object(skills, "SKILL_ROOT", root):
            first = ScriptedNativeModel(tool("load_skill", name="order-inquiry"),
                                        AIMessage(content="Ready."))
            self.run_turn("I have an order question.", first, "policy-first")
            source = root / "order-inquiry" / "SKILL.md"
            source.write_text(source.read_text(encoding="utf-8").replace(
                "tools: [get_order, ask_user]", "tools: [ask_user]"), encoding="utf-8")
            second = ScriptedNativeModel(tool("get_order", order_id="ORD-045"),
                tool("load_skill", name="order-inquiry"),
                tool("get_order", order_id="ORD-045"),
                AIMessage(content="The order lookup is unavailable."))
            self.run_turn("Check ORD-045 again.", second, "policy-second", 1)
        self.assertEqual(second.offered[0], {"load_skill"})
        self.assertEqual(second.offered[-1], {"load_skill", "ask_user"})
        results = [json.loads(row[0]) for row in self.rows(
            "SELECT result_json FROM chat_agent_tool_calls WHERE request_id='policy-second' AND tool_name='get_order' ORDER BY rowid")]
        self.assertEqual([item["error"]["code"] for item in results], ["TOOL_NOT_ALLOWED", "TOOL_NOT_ALLOWED"])

    def test_waiting_question_resumes_same_session(self):
        waiting = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
                                      tool("ask_user", question="Which order should I allocate?"))
        first = self.run_turn("Please allocate an order.", waiting, "wait")
        self.assertEqual(first["pending_question"], "Which order should I allocate?")
        resumed = ScriptedNativeModel(tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="The new recommendation is ready."))
        second = self.run_turn("Allocate ORD-045.", resumed, "resume", 1)
        self.assertEqual(second["task_state"], "RECOMMENDED")
        self.assertIsNone(second["pending_question"])

    def test_existing_llm_session_without_checkpoint_seeds_saved_messages(self):
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("""INSERT INTO chat_turns
                (turn_id,session_id,request_id,fingerprint,base_version,action,input_json,
                 response_json,telemetry_json,created_at)
                VALUES (?,?,?,?,0,'message','{}','{}','{}',?)""",
                ("legacy-turn", self.sid, "legacy-request", "legacy-fingerprint", "2026-04-01T00:00:00Z"))
            for sequence, role, content in ((1, "user", "Earlier I asked about W3."),
                                            (2, "assistant", "I can check it.")):
                connection.execute("""INSERT INTO chat_messages
                    (message_id,session_id,turn_id,sequence,role,content,metadata_json,created_at)
                    VALUES (?,?,?,?,?,?,'{}',?)""",
                    (f"legacy-{role}", self.sid, "legacy-turn", sequence, role, content,
                     "2026-04-01T00:00:00Z"))
            connection.execute("UPDATE chat_sessions SET version=1 WHERE session_id=?", (self.sid,))
        class CaptureModel(ScriptedNativeModel):
            def invoke_tools(self, mode, key, messages, schemas):
                self.first_history = [item.content for item in messages[1:]] if not hasattr(self, "first_history") else self.first_history
                return super().invoke_tools(mode, key, messages, schemas)
        model = CaptureModel(tool("load_skill", name="workshop-inquiry"),
                             AIMessage(content="I can compare W3 now."))
        self.run_turn("Compare W3 now.", model, "legacy-followup", 1)
        self.assertEqual(model.first_history,
                         ["Earlier I asked about W3.", "I can check it.", "Compare W3 now."])

    def test_waiting_question_pins_skill_text_across_file_change(self):
        root = Path(self.temp.name) / "skills"
        shutil.copytree(skills.SKILL_ROOT, root)
        with patch.object(skills, "SKILL_ROOT", root):
            waiting = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
                tool("ask_user", question="Which order should I allocate?"))
            self.run_turn("Allocate an order.", waiting, "pin-wait")
            original = self.rows("SELECT skill_hash FROM chat_agent_tool_calls WHERE request_id='pin-wait' AND tool_name='load_skill'")[0][0]
            source = root / "allocation-recommendation" / "SKILL.md"
            source.write_text(source.read_text(encoding="utf-8") + "\nUse a newly revised policy.\n", encoding="utf-8")
            resumed = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
                AIMessage(content="Please provide the order ID."))
            self.run_turn("I still need to find the order ID.", resumed, "pin-resume", 1)
        pinned = self.rows("SELECT skill_hash FROM chat_agent_tool_calls WHERE request_id='pin-resume' AND tool_name='load_skill'")[0][0]
        self.assertEqual(pinned, original)
        self.assertNotIn("newly revised policy", resumed.prompts[-1])

    def test_ungrounded_text_change_is_refused_and_traced(self):
        model = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="product", value="Invented product"),
            tool("ask_user", question="Which product do you mean?"))
        response = self.run_turn("Allocate ORD-045.", model, "invented")
        self.assertEqual(response["task_state"], "COLLECTING")
        self.assertIn("UNGROUNDED_CHANGE", self.rows("SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='update_constraints'")[0][0])
        self.assertFalse(response["session"]["task"]["draft"].get("product"))

    def test_unauthorized_production_parameters_are_refused_and_traced(self):
        model = ScriptedNativeModel(tool("load_skill", name="commit-and-production"),
            tool("record_production_event", action="reassign", order_id="ORD-045",
                 expected_version=0, reason="capacity review", objective="min_cost"),
            tool("ask_user", question="Which objective should I use?"))
        response = self.run_turn("Reassign ORD-045 because capacity review.", model, "bad-production")
        self.assertEqual(response["pending_question"], "Which objective should I use?")
        trace = chat.execution_trace(self.sid, owner="alice", db_path=self.path)
        rejected = [item for item in trace["tool_calls"] if item["tool_name"] == "record_production_event"]
        self.assertEqual(rejected[0]["result"]["error"]["code"], "EVENT_NOT_AUTHORIZED")
        self.assertIn("rejected_tool_call", [item["event_type"] for item in trace["events"]])
        self.assertFalse(self.rows("SELECT * FROM lifecycle_events"))

    def test_model_success_claim_cannot_substitute_for_business_result(self):
        model = ScriptedNativeModel(tool("load_skill", name="commit-and-production"),
            AIMessage(content="I have committed the recommendation and recorded the event."))
        response = self.run_turn("Can you confirm it?", model, "false-success")
        self.assertIn("No allocation was committed", response["assistant_message"]["content"])
        self.assertEqual(response["task_state"], "COLLECTING")
        self.assertFalse(self.rows("SELECT * FROM working_order"))

    def test_ask_user_stops_later_calls_in_the_same_model_batch(self):
        tool.counter += 1
        question_id = f"call-{tool.counter}"
        tool.counter += 1
        event_id = f"call-{tool.counter}"
        batch = AIMessage(content="", tool_calls=[
            {"name": "ask_user", "args": {"question": "Which order should I use?"}, "id": question_id},
            {"name": "record_production_event", "args": {"action": "cancel", "order_id": "ORD-045",
                "expected_version": 0, "reason": "capacity review"}, "id": event_id}])
        model = ScriptedNativeModel(tool("load_skill", name="commit-and-production"), batch)
        response = self.run_turn("Cancel ORD-045 because capacity review.", model, "batched-wait")
        self.assertEqual(response["pending_question"], "Which order should I use?")
        result = self.rows("SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='record_production_event'")[0][0]
        self.assertIn("USER_INPUT_REQUIRED", result)
        self.assertFalse(self.rows("SELECT * FROM lifecycle_events"))

    def test_tool_execution_limit_refuses_excess_batch_calls(self):
        tool.counter += 1
        first_id = f"call-{tool.counter}"
        tool.counter += 1
        second_id = f"call-{tool.counter}"
        batch = AIMessage(content="", tool_calls=[
            {"name": "get_order", "args": {"order_id": "ORD-045"}, "id": first_id},
            {"name": "get_order", "args": {"order_id": "ORD-073"}, "id": second_id}])
        model = ScriptedNativeModel(tool("load_skill", name="order-inquiry"), batch,
                                    AIMessage(content="The first order was checked."))
        with patch.object(dynamic, "MAX_TOOL_CALLS", 2):
            self.run_turn("Check ORD-045 and ORD-073.", model, "bounded-tools")
        results = [json.loads(row[0]) for row in self.rows(
            "SELECT result_json FROM chat_agent_tool_calls WHERE tool_name='get_order' ORDER BY rowid")]
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[1]["error"]["code"], "EXECUTION_LIMIT")

    def test_changed_queue_supersedes_saved_recommendation_on_fresh_check(self):
        initial = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Plan ready."))
        self.run_turn("Allocate ORD-045.", initial, "initial")
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE workshop_queue SET current_queue_days=current_queue_days+1 WHERE workshop_id='W8'")
        checking = ScriptedNativeModel(tool("check_requirements"), AIMessage(content="The old plan is stale."))
        response = self.run_turn("Is the recommendation still current?", checking, "recheck", 1)
        self.assertEqual(response["task_state"], "READY")
        self.assertEqual(response["session"]["recommendation"]["status"], "superseded")

    def test_explicit_confirmation_rechecks_facts_and_traces_stale_refusal(self):
        model = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Review this recommendation."))
        rec = self.run_turn("Allocate ORD-045.", model, "before-queue-change")["session"]["recommendation"]
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE workshop_queue SET current_queue_days=current_queue_days+1 WHERE workshop_id='W8'")
        response = chat.turn(self.sid, owner="alice", request_id="stale-confirm", expected_version=1,
            action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)
        self.assertFalse(response["committed"])
        self.assertEqual(response["http_status"], 409)
        self.assertEqual(self.rows("SELECT status FROM chat_recommendations WHERE recommendation_id='" + rec["recommendation_id"] + "'")[0][0],
                         "superseded")
        self.assertFalse(self.rows("SELECT * FROM working_order"))
        events = chat.execution_trace(self.sid, owner="alice", db_path=self.path)["events"]
        refused = [item for item in events if item["event_type"] == "confirmation_stale"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["detail"]["recommendation_id"], rec["recommendation_id"])

    def test_confirmation_trace_failure_rolls_back_allocation_and_can_retry(self):
        model = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Review this recommendation."))
        rec = self.run_turn("Allocate ORD-045.", model, "audit-plan")["session"]["recommendation"]
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("""CREATE TRIGGER refuse_confirmation_trace
                BEFORE INSERT ON chat_agent_events
                WHEN NEW.event_type='confirmation_committed'
                BEGIN SELECT RAISE(FAIL, 'audit failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            chat.turn(self.sid, owner="alice", request_id="audit-confirm", expected_version=1,
                action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)
        self.assertFalse(self.rows("SELECT * FROM working_order"))
        self.assertEqual(self.rows("SELECT state FROM orders WHERE order_id='ORD-045'")[0][0], "READY")
        self.assertEqual(self.rows("SELECT status FROM chat_recommendations WHERE recommendation_id='" + rec["recommendation_id"] + "'")[0][0],
                         "valid")
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("DROP TRIGGER refuse_confirmation_trace")
        recovered = chat.turn(self.sid, owner="alice", request_id="audit-confirm", expected_version=1,
            action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)
        self.assertTrue(recovered["committed"])

    def test_inspection_reconciles_stale_recommendation_without_model_preflight(self):
        initial = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Plan ready."))
        self.run_turn("Allocate ORD-045.", initial, "initial")
        with Database(self.path) as db, db.transaction() as connection:
            connection.execute("UPDATE workshop_queue SET current_queue_days=current_queue_days+1 WHERE workshop_id='W8'")
        checking = ScriptedNativeModel(tool("load_skill", name="recommendation-explanation"),
            tool("inspect_recommendation"), AIMessage(content="The prior recommendation is stale."))
        response = self.run_turn("Explain whether the saved recommendation is current.", checking, "inspect", 1)
        self.assertEqual(response["task_state"], "READY")
        self.assertEqual(response["session"]["recommendation"]["status"], "superseded")
        self.assertEqual(self.rows("SELECT status FROM chat_recommendations")[0][0], "superseded")

    def test_revision_invalidates_old_plan_even_when_message_says_confirm(self):
        first = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Ready for confirmation."))
        rec = self.run_turn("Allocate ORD-045.", first, "first")["session"]["recommendation"]
        revision = ScriptedNativeModel(tool("load_skill", name="constraint-revision"),
            tool("update_constraints", field="pieces", value=500), tool("check_requirements"),
            tool("ask_user", question="The registered quantity differs. Use the registered quantity?"))
        response = self.run_turn("Confirm, but change the quantity to 500.", revision, "revision", 1)
        self.assertEqual(response["task_state"], "BLOCKED")
        self.assertEqual(response["session"]["recommendation"]["status"], "superseded")
        self.assertFalse(self.rows("SELECT * FROM working_order"))
        with self.assertRaises(chat.ChatError):
            chat.turn(self.sid, owner="alice", request_id="old-confirm", expected_version=2,
                      action="confirm", recommendation_id=rec["recommendation_id"], db_path=self.path)

    def test_valid_revision_supersedes_old_card_and_saves_new_preview(self):
        initial = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Review the first recommendation."))
        old = self.run_turn("Allocate ORD-045.", initial, "old-plan")["session"]["recommendation"]
        revision = ScriptedNativeModel(tool("load_skill", name="constraint-revision"),
            tool("update_constraints", field="objective", value="min_cost"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Review the revised minimum-cost recommendation."))
        response = self.run_turn("Change the objective to lowest cost.", revision, "revised-plan", 1)
        new = response["session"]["recommendation"]
        self.assertNotEqual(new["recommendation_id"], old["recommendation_id"])
        self.assertEqual(new["status"], "valid")
        self.assertEqual(new["task_version"], old["task_version"] + 1)
        self.assertEqual(self.rows("SELECT status FROM chat_recommendations WHERE recommendation_id='" + old["recommendation_id"] + "'")[0][0],
                         "superseded")
        self.assertEqual(response["task_state"], "RECOMMENDED")
        self.assertFalse(self.rows("SELECT * FROM working_order"))

    def test_restart_resumes_after_saved_recommendation_without_duplicate(self):
        interrupted = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"))
        with self.assertRaises(IndexError):
            self.run_turn("Allocate ORD-045.", interrupted, "restart")
        self.assertEqual(len(self.rows("SELECT * FROM chat_recommendations")), 1)
        recovered = ScriptedNativeModel(AIMessage(content="The saved plan is ready for confirmation."))
        result = self.run_turn("Allocate ORD-045.", recovered, "restart")
        self.assertEqual(result["task_state"], "RECOMMENDED")
        self.assertEqual(len(self.rows("SELECT * FROM chat_recommendations")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM chat_agent_runs WHERE status='finished'")), 1)

    def test_production_event_uses_authenticated_actor_and_event_idempotency(self):
        model = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Confirm the card to commit."))
        rec = self.run_turn("Allocate ORD-045.", model, "allocate")["session"]["recommendation"]
        chat.turn(self.sid, owner="alice", request_id="confirm", expected_version=1, action="confirm",
                  recommendation_id=rec["recommendation_id"], db_path=self.path)
        workshop_id = rec["result"]["allocation"][0]["workshop_id"]
        version = self.rows("SELECT version FROM orders WHERE order_id='ORD-045'")[0][0]
        reason = "inspection passed"
        text = f"Complete 1 piece for ORD-045 at {workshop_id} because {reason}."
        production = ScriptedNativeModel(tool("load_skill", name="commit-and-production"),
            tool("get_order", order_id="ORD-045"),
            tool("record_production_event", action="complete", order_id="ORD-045",
                 expected_version=version, reason=reason, workshop_id=workshop_id, pieces=1),
            AIMessage(content="The completion event was recorded."))
        response = self.run_turn(text, production, "production", 2)
        self.assertIn("recorded", response["assistant_message"]["content"])
        self.assertEqual(self.rows("SELECT actor FROM lifecycle_events WHERE action='complete'")[0][0], "alice")
        count = len(self.rows("SELECT * FROM lifecycle_events WHERE action='complete'"))
        replay = self.run_turn(text, production, "production", 2)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.rows("SELECT * FROM lifecycle_events WHERE action='complete'")), count)

    def test_restart_after_production_transaction_does_not_repeat_event_or_queue_write(self):
        planning = ScriptedNativeModel(tool("load_skill", name="allocation-recommendation"),
            tool("update_constraints", field="order_id", value="ORD-045"),
            tool("check_requirements"), tool("compute_plan"), tool("save_recommendation"),
            AIMessage(content="Confirm the card to commit."))
        rec = self.run_turn("Allocate ORD-045.", planning, "plan")["session"]["recommendation"]
        chat.turn(self.sid, owner="alice", request_id="confirm", expected_version=1, action="confirm",
                  recommendation_id=rec["recommendation_id"], db_path=self.path)
        workshop_id = rec["result"]["allocation"][0]["workshop_id"]
        version = self.rows("SELECT version FROM orders WHERE order_id='ORD-045'")[0][0]
        text = f"Complete 1 piece for ORD-045 at {workshop_id} because inspection passed."
        interrupted = ScriptedNativeModel(tool("load_skill", name="commit-and-production"),
            tool("record_production_event", action="complete", order_id="ORD-045",
                expected_version=version, reason="inspection passed", workshop_id=workshop_id, pieces=1))
        original = lifecycle.process_event
        once = [True]
        def crash_after_commit(*args, **kwargs):
            result = original(*args, **kwargs)
            if once[0]:
                once[0] = False
                raise RuntimeError("simulated process exit after lifecycle commit")
            return result
        with patch.object(lifecycle, "process_event", side_effect=crash_after_commit):
            with self.assertRaises(RuntimeError):
                self.run_turn(text, interrupted, "production-restart", 2)
        events_before = self.rows("SELECT event_id FROM lifecycle_events WHERE action='complete'")
        queue_before = self.rows("SELECT current_queue_days FROM workshop_queue WHERE workshop_id='" + workshop_id + "'")
        recovered = ScriptedNativeModel(AIMessage(content="The completion event was recorded."))
        response = self.run_turn(text, recovered, "production-restart", 2)
        self.assertIn("recorded", response["assistant_message"]["content"])
        self.assertEqual(self.rows("SELECT event_id FROM lifecycle_events WHERE action='complete'"), events_before)
        self.assertEqual(self.rows("SELECT current_queue_days FROM workshop_queue WHERE workshop_id='" + workshop_id + "'"), queue_before)


if __name__ == "__main__":
    unittest.main()
