"""Service-side handlers for Agent Tool names.

Tool argument validation and LangChain binding stay in ``app.tools``.
This module applies task-state guards and calls allocation / DB repositories.
Do not import it from HTTP routes; go through ``app.tools.operations``.
"""
from dataclasses import asdict
from datetime import date
import re
from app.services import scoring as original_scores
from app.db.workshop_repository import get_all
from app.services.eligibility import exclusion_reason
from app.services import allocation
from app.services.allocation_preflight import preflight
from app.services.conversation_context import build_context
from app.services.interpretation import validate_interpretation
from app.services.constraint_patches import apply_interpretation
from app.schemas.chat import TurnInterpretation
from app.db import chat_repository
from app.db.order_repository import get_order
from app.schemas.tool import ToolFailure

ALLOWED_TASK_STATES = {
    "update_constraints": frozenset({"COLLECTING", "BLOCKED", "READY", "RECOMMENDED"}),
    "check_requirements": frozenset({"COLLECTING", "BLOCKED", "READY", "RECOMMENDED"}),
    "compute_plan": frozenset({"READY", "RECOMMENDED"}),
    "save_recommendation": frozenset({"READY", "RECOMMENDED"}),
}

def _retain_preparation_provenance(task, report):
    differences = task.get("report", {}).get("resolved_differences")
    if differences:
        report["resolved_differences"] = differences
    return report


def execute(name, args, *, connection, session, as_of, user_message, plan=None):
    """Return (verified data, graph plan update, pending question). Caller owns transaction."""
    task = session["task"]
    state = task["state"]
    if name in ALLOWED_TASK_STATES and state not in ALLOWED_TASK_STATES[name]:
        raise ToolFailure("INVALID_TASK_STATE", f"{name} is not allowed while the task is {state}.")
    if name == "get_order":
        row = get_order(connection, args["order_id"])
        if row is None:
            raise ToolFailure("ORDER_NOT_FOUND", "No registered order has that ID.")
        value = row
        value["remaining_pieces"] = value["pieces"] - value["completed_pieces"]
        return value, None, None
    if name in ("list_workshops", "get_queue", "score_workshop"):
        workshops = get_all(connection, as_of)
        if name == "list_workshops":
            selected = [w for w in workshops if not args.get("workshop_id") or w.workshop_id == args["workshop_id"]]
            if not selected:
                raise ToolFailure("WORKSHOP_NOT_FOUND", "No registered workshop has that ID.")
            return [{**asdict(w), "makes": sorted(w.makes)} for w in selected], None, None
        workshop = next((w for w in workshops if w.workshop_id == args["workshop_id"]), None)
        if workshop is None:
            raise ToolFailure("WORKSHOP_NOT_FOUND", "No registered workshop has that ID.")
        if name == "get_queue":
            return {"workshop_id": workshop.workshop_id, "queue_days": workshop.queue_days,
                    "as_of_date": as_of.isoformat()}, None, None
        row = get_order(connection, args["order_id"])
        if row is None:
            raise ToolFailure("ORDER_NOT_FOUND", "No registered order has that ID.")
        order = row
        pieces = args.get("pieces", order["pieces"] - order["completed_pieces"])
        if type(pieces) is not int or pieces <= 0 or workshop.capacity <= 0:
            raise ToolFailure("INVALID_QUANTITY", "A positive integer batch and positive workshop capacity are required.")
        batch = {"pieces": pieces, "due_date": date.fromisoformat(order["due_date"]), "sent_date": as_of}
        queues = {workshop.workshop_id: workshop.queue_days}
        data = {"workshop_id": workshop.workshop_id, "order_id": order["order_id"], "pieces": pieces,
                "sent_date": as_of.isoformat(), "queue_days": workshop.queue_days,
                "estimated_completion_days": original_scores.get_estimated_completion_time(workshop, batch, queues),
                "lateness_score_days": original_scores.get_lateness_score(workshop, batch, queues),
                "defect_score": original_scores.get_defect_score(workshop, batch),
                "original_hybrid_score": original_scores.get_hybrid_score(workshop, batch, queues),
                "eligibility_rejection": exclusion_reason(workshop, order["category"], pieces,
                    task["draft"].get("exclusion") or []),
                "score_semantics": "Original single-workshop formulas; original hybrid returns defect rate only if on time, otherwise 10000. The planner uses a different weighted objective."}
        return data, None, None
    if name == "inspect_recommendation":
        from app.services.chat import reconcile_recommendation
        reconcile_recommendation(connection, session)
        rec = chat_repository.latest_recommendation(connection, session["session_id"])
        if rec is None:
            raise ToolFailure("RECOMMENDATION_NOT_FOUND", "This session has no saved recommendation.")
        return rec, None, None
    if name == "ask_user":
        if re.search(r"[\u4e00-\u9fff]", args["question"]):
            raise ToolFailure("ENGLISH_REQUIRED", "Ask the question in English.")
        return {"question": args["question"]}, None, args["question"]
    if name == "update_constraints":
        field = args["field"]
        operation = args.get("operation", "set")
        if field not in task["draft"] or field in ("parse_status", "missing_fields", "ambiguities"):
            raise ToolFailure("INVALID_FIELD", "This requirement field cannot be changed.")
        if field in ("customer", "product", "category") and operation not in ("unset", "undo"):
            value = args.get("value")
            mentioned = isinstance(value, str) and value.casefold() in user_message.casefold()
            registered = False
            if not mentioned and "registered" in user_message.casefold() and task["draft"].get("order_id"):
                order = get_order(connection, task["draft"]["order_id"])
                registered = bool(order and order[field] == value)
            if not mentioned and not registered:
                raise ToolFailure("UNGROUNDED_CHANGE", "The value must appear in the current user message or match an explicitly requested registered order value.")
        context = build_context(connection, session)
        interpretation = TurnInterpretation(intent="modify_constraints", patch_operations=[{
            "op": operation, "field": field, "value": args.get("value"),
            "evidence": {"message_sequence": context["current_sequence"], "quote": user_message}}])
        try:
            validate_interpretation(interpretation, user_message, context)
        except (ValueError, KeyError, TypeError) as error:
            raise ToolFailure("UNGROUNDED_CHANGE", f"The requested change is not supported by the current user message: {error}") from None
        revised = apply_interpretation(task, interpretation, context["current_sequence"])
        revised["task_version"] += 1
        revised["state"] = "COLLECTING"
        revised["report"] = {}
        chat_repository.supersede_current(connection, session["session_id"])
        chat_repository.save_task(connection, revised)
        return {"draft": revised["draft"], "task_version": revised["task_version"],
                "state": revised["state"], "previous_recommendation_invalidated": True}, None, None
    if name == "check_requirements":
        report, _, _, facts_hash = preflight(connection, task["draft"], as_of, task["issues"], task["sources"])
        _retain_preparation_provenance(task, report)
        task["report"] = report
        current_rec = chat_repository.latest_recommendation(connection, session["session_id"])
        recommendation_current = bool(current_rec and current_rec["status"] == "valid" and
                                      current_rec["facts_hash"] == facts_hash and
                                      current_rec["task_version"] == task["task_version"])
        task["state"] = ("RECOMMENDED" if recommendation_current else "READY") if report["ready_for_planning"] else "BLOCKED"
        if not recommendation_current:
            chat_repository.supersede_current(connection, session["session_id"])
        chat_repository.save_task(connection, task)
        return {"state": task["state"], "report": report, "facts_hash": facts_hash}, None, None
    if name == "compute_plan":
        if state not in ("READY", "RECOMMENDED"):
            raise ToolFailure("INVALID_TASK_STATE", "Run check_requirements successfully before computing a plan.")
        report, result, _, facts_hash, plan_hash = allocation.recommend(
            connection, task["draft"], as_of, task["issues"], task["sources"])
        _retain_preparation_provenance(task, report)
        if not report["ready_for_recommendation"]:
            task["state"] = "BLOCKED"
            task["report"] = report
            chat_repository.save_task(connection, task)
            chat_repository.supersede_current(connection, session["session_id"])
            raise ToolFailure("PLAN_BLOCKED", "The current constraints or business data do not yield a valid plan: " +
                              ", ".join(p["code"] for p in report["blocking_issues"]))
        data = {"result": result, "report": report, "facts_hash": facts_hash, "plan_hash": plan_hash,
                "task_version": task["task_version"]}
        return data, data, None
    if name == "save_recommendation":
        if state not in ("READY", "RECOMMENDED") or not plan:
            raise ToolFailure("PLAN_REQUIRED", "Compute a valid plan in this run before saving a recommendation.")
        report, result, _, facts_hash, plan_hash = allocation.recommend(
            connection, task["draft"], as_of, task["issues"], task["sources"])
        _retain_preparation_provenance(task, report)
        if (not report["ready_for_recommendation"] or plan_hash != plan["plan_hash"] or
                facts_hash != plan["facts_hash"] or task["task_version"] != plan["task_version"]):
            task["state"] = "BLOCKED"
            task["report"] = report
            chat_repository.save_task(connection, task)
            chat_repository.supersede_current(connection, session["session_id"])
            raise ToolFailure("STALE_PLAN", "Business facts, requirements, or the computed plan changed; recompute before saving.")
        rec = chat_repository.insert_recommendation(connection, session, result, facts_hash, plan_hash)
        task["state"] = "RECOMMENDED"
        task["report"] = report
        chat_repository.save_task(connection, task)
        return {"recommendation_id": rec["recommendation_id"], "task_version": rec["task_version"],
                "status": rec["status"], "result": rec["result"]}, None, None
    raise ToolFailure("UNKNOWN_TOOL", "The requested tool is not registered.")
