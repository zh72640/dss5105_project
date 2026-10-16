"""Run a reproducible native-tool graph acceptance trace in an isolated database."""
from datetime import date
from pathlib import Path
import json
import tempfile

from langchain_core.messages import AIMessage

from app.db.database import Database
from app.services.chat import service as chat
from app.config.model_settings import ModelSpec


class ScriptedNativeModel:
    """Supply native tool calls while exercising the real graph, tools, and services."""

    def __init__(self, *responses, allocation=False):
        self.responses = list(responses)
        self.allocation = allocation
        self.offered_tools = []

    def resolve(self, mode, key):
        return ModelSpec("mock", "openai", "mock", "test")

    def get_model(self, mode, key):
        return self

    def bind_tools(self, schemas):
        self.offered_tools.append([tool["function"]["name"] if isinstance(tool, dict) else tool.name
                                   for tool in schemas])
        return self

    def invoke(self, messages):
        first = messages[0]["content"] if isinstance(messages[0], dict) else messages[0].content
        if "Classify the current user message" in first:
            return AIMessage(content=json.dumps({"task_type": "allocation" if self.allocation else "compat"}))
        if "Extract the user's allocation request" in first:
            return AIMessage(content=json.dumps({"intent": "allocate_request", "patch_operations": [{
                "op": "set", "field": "order_id", "value": "ORD-045", "quote": messages[-1]["content"]}]}))
        return self.responses.pop(0)

def call(tool_name, **arguments):
    call.sequence += 1
    return AIMessage(content="", tool_calls=[{
        "name": tool_name, "args": arguments, "id": f"acceptance-{call.sequence}"}])


call.sequence = 0


def turn(session_id, db_path, request_id, version, message, model):
    return chat.turn(session_id, owner="acceptance", db_path=db_path,
        request_id=request_id, expected_version=version, message=message, registry=model)


def run(output_path=Path("evaluation/results/dynamic_agent_acceptance.json")):
    with tempfile.TemporaryDirectory(prefix="dispatch-agent-acceptance-") as directory:
        db_path = Path(directory) / "acceptance.sqlite3"
        business_date = date(2026, 4, 1)
        query_session = chat.create(owner="acceptance", request_id="accept-query-create",
            db_path=db_path, as_of=business_date, mode="llm")["session_id"]
        query_model = ScriptedNativeModel(
            call("load_skill", name="order-inquiry"),
            call("get_order", order_id="ORD-045"),
            AIMessage(content="ORD-045 is ready for allocation."))
        query = turn(query_session, db_path, "accept-query", 0,
            "What is the status of ORD-045?", query_model)

        allocation_session = chat.create(owner="acceptance",
            request_id="accept-allocation-create", db_path=db_path, as_of=business_date,
            mode="llm")["session_id"]
        allocation_model = ScriptedNativeModel(
            call("check_requirements"),
            call("compute_plan"),
            call("save_recommendation"),
            AIMessage(content="A checked recommendation is ready for your confirmation."), allocation=True)
        recommendation = turn(allocation_session, db_path, "accept-allocation", 0,
            "Allocate ORD-045.", allocation_model)
        with Database(db_path) as db:
            preview_production_rows = db.connection.execute(
                "SELECT COUNT(*) FROM working_order").fetchone()[0]
        old_card = recommendation["session"]["recommendation"]
        revision_model = ScriptedNativeModel(
            call("load_skill", name="constraint-revision"),
            call("update_constraints", field="objective", value="min_cost"),
            call("check_requirements"),
            call("compute_plan"),
            call("save_recommendation"),
            AIMessage(content="A revised minimum-cost recommendation is ready for confirmation."))
        revision = turn(allocation_session, db_path, "accept-revision", 1,
            "Change the objective to lowest cost.", revision_model)
        with Database(db_path) as db:
            revised_preview_production_rows = db.connection.execute(
                "SELECT COUNT(*) FROM working_order").fetchone()[0]
        card = revision["session"]["recommendation"]
        confirmation = chat.turn(allocation_session, owner="acceptance",
            db_path=db_path, request_id="accept-confirm", expected_version=2,
            action="confirm", recommendation_id=card["recommendation_id"])
        replay = chat.turn(allocation_session, owner="acceptance",
            db_path=db_path, request_id="accept-confirm", expected_version=2,
            action="confirm", recommendation_id=card["recommendation_id"])

        workshop_id = card["result"]["allocation"][0]["workshop_id"]
        with Database(db_path) as db:
            order_version = db.connection.execute(
                "SELECT version FROM orders WHERE order_id='ORD-045'").fetchone()[0]
        production_model = ScriptedNativeModel(
            call("load_skill", name="commit-and-production"),
            call("get_order", order_id="ORD-045"),
            call("record_production_event", action="complete", order_id="ORD-045",
                 expected_version=order_version, reason="inspection passed",
                 workshop_id=workshop_id, pieces=1),
            AIMessage(content="The completion event was recorded."))
        production = turn(allocation_session, db_path, "accept-production", 3,
            f"Complete 1 piece for ORD-045 at {workshop_id} because inspection passed.",
            production_model)

        wait_session = chat.create(owner="acceptance", request_id="accept-wait-create",
            db_path=db_path, as_of=business_date, mode="llm")["session_id"]
        waiting_model = ScriptedNativeModel(
            call("load_skill", name="order-inquiry"),
            call("ask_user", question="Which order should I check?"))
        waiting = turn(wait_session, db_path, "accept-wait", 0,
            "Please check an order.", waiting_model)
        resumed_model = ScriptedNativeModel(
            call("get_order", order_id="ORD-045"),
            AIMessage(content="ORD-045 is working; its current state came from the order tool."))
        resumed = turn(wait_session, db_path, "accept-resume", 1,
            "Check ORD-045.", resumed_model)

        with Database(db_path) as db:
            connection = db.connection
            order = dict(connection.execute(
                "SELECT order_id,state,version,pieces,completed_pieces FROM orders "
                "WHERE order_id='ORD-045'").fetchone())
            allocation_rows = [dict(row) for row in connection.execute(
                "SELECT order_id,workshop_id,pieces,completed_pieces FROM working_order "
                "WHERE order_id='ORD-045' ORDER BY workshop_id")]
            event_count = connection.execute(
                "SELECT COUNT(*) FROM lifecycle_events WHERE action='complete' "
                "AND order_id='ORD-045'").fetchone()[0]
            old_card_status = connection.execute(
                "SELECT status FROM chat_recommendations WHERE recommendation_id=?",
                (old_card["recommendation_id"],)).fetchone()[0]
        report = {
            "method": "Scripted AIMessage.tool_calls through the production LangGraph and tools; no live provider call",
            "business_date": business_date.isoformat(),
            "order_query": {
                "reply": query["assistant_message"]["content"],
                "offered_tools": query_model.offered_tools,
                "trace": chat.execution_trace(query_session, owner="acceptance", db_path=db_path),
            },
            "allocation": {
                "response_type": recommendation["type"],
                "explanation": recommendation["explanation"],
                "result": recommendation["allocation"],
                "task_state_after_recommendation": recommendation["task_state"],
                "old_recommendation_id": old_card["recommendation_id"],
                "old_recommendation_status_after_revision": old_card_status,
                "recommendation_id": card["recommendation_id"],
                "production_rows_before_confirmation": preview_production_rows,
                "production_rows_after_revision_before_confirmation": revised_preview_production_rows,
                "committed": confirmation["committed"],
                "confirmation_replayed": replay["replayed"],
                "offered_tools": allocation_model.offered_tools,
                "revision_offered_tools": revision_model.offered_tools,
                "trace": chat.execution_trace(allocation_session, owner="acceptance", db_path=db_path),
            },
            "production": {
                "reply": production["assistant_message"]["content"],
                "offered_tools": production_model.offered_tools,
                "event_count": event_count,
            },
            "wait_and_resume": {
                "question": waiting["pending_question"],
                "pending_after_resume": resumed["pending_question"],
                "resumed_reply": resumed["assistant_message"]["content"],
                "offered_tools_before_wait": waiting_model.offered_tools,
                "offered_tools_after_resume": resumed_model.offered_tools,
                "trace": chat.execution_trace(wait_session, owner="acceptance", db_path=db_path),
            },
            "database_after": {"order": order, "working_order": allocation_rows},
        }
        if ([item["tool_name"] for item in report["order_query"]["trace"]["tool_calls"]]
                != ["load_skill", "get_order"]):
            raise AssertionError("The order query did not use the inquiry Toolset.")
        if (recommendation["task_state"] != "RECOMMENDED" or revision["task_state"] != "RECOMMENDED"
                or old_card["recommendation_id"] == card["recommendation_id"]
                or old_card_status != "superseded"):
            raise AssertionError("Revision did not replace the recommendation under the state guard.")
        if (recommendation["type"] != "allocation" or not recommendation["explanation"] or
                recommendation["explanation"] != recommendation["assistant_message"]["content"] or
                recommendation["allocation"]["recommendation_id"] != old_card["recommendation_id"]):
            raise AssertionError("The response did not package the explanation with its saved allocation.")
        allocation_model_calls = [event["detail"] for event in report["allocation"]["trace"]["events"]
            if event["request_id"] == "accept-allocation" and event["event_type"] == "model_call"]
        if ([item["stage"] for item in allocation_model_calls].count("explanation") != 1 or
                any(item["stage"] == "response" for item in allocation_model_calls)):
            raise AssertionError("Explanation and deterministic response stages were not separated.")
        if preview_production_rows != 0 or revised_preview_production_rows != 0:
            raise AssertionError("A recommendation wrote production allocation before confirmation.")
        if not confirmation["committed"] or not replay["replayed"] or len(allocation_rows) != 1:
            raise AssertionError("Explicit confirmation or its idempotent replay failed.")
        commit_events = [event for event in report["allocation"]["trace"]["events"]
                         if event["event_type"] == "confirmation_committed"]
        if (len(commit_events) != 1 or
                commit_events[0]["detail"]["recommendation_id"] != card["recommendation_id"]):
            raise AssertionError("The confirmation transition is missing from the audit trace.")
        if event_count != 1 or order["completed_pieces"] != 1:
            raise AssertionError("The production event was not applied exactly once.")
        if not waiting["pending_question"] or resumed["pending_question"] is not None:
            raise AssertionError("The saved question did not resume on the next message.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        return report


if __name__ == "__main__":
    report = run()
    print(json.dumps({
        "output": "evaluation/results/dynamic_agent_acceptance.json",
        "query_tools": [item["tool_name"] for item in report["order_query"]["trace"]["tool_calls"]],
        "allocation_tools": [item["tool_name"] for item in report["allocation"]["trace"]["tool_calls"]],
        "preview_production_rows": report["allocation"]["production_rows_before_confirmation"],
        "revised_preview_production_rows": report["allocation"]["production_rows_after_revision_before_confirmation"],
        "old_recommendation_status_after_revision": report["allocation"]["old_recommendation_status_after_revision"],
        "committed": report["allocation"]["committed"],
        "confirmation_replayed": report["allocation"]["confirmation_replayed"],
        "production_events": report["production"]["event_count"],
        "resumed_question_cleared": report["wait_and_resume"]["pending_after_resume"] is None,
    }, indent=2))
