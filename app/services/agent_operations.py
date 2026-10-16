"""Named Service helpers for Agent Tool business operations.

Task-state guards and Chat allocation persistence live here.
Do not import from HTTP routes; Agent Tools call these functions.
"""
from app.db import chat_repository
from app.db.order_repository import get_order
from app.services import allocation
from app.services.allocation_preflight import preflight
from app.services.conversation_context import build_context
from app.services.interpretation import validate_interpretation
from app.services.constraint_patches import apply_interpretation
from app.schemas.chat import TurnInterpretation
from app.schemas.tool import ToolFailure

ALLOWED_TASK_STATES = {
    "update_constraints": frozenset({"COLLECTING", "BLOCKED", "READY", "RECOMMENDED"}),
    "check_requirements": frozenset({"COLLECTING", "BLOCKED", "READY", "RECOMMENDED"}),
    "compute_plan": frozenset({"READY", "RECOMMENDED"}),
    "save_recommendation": frozenset({"READY", "RECOMMENDED"}),
}


def _require_task_state(name, state):
    allowed = ALLOWED_TASK_STATES.get(name)
    if allowed is not None and state not in allowed:
        raise ToolFailure("INVALID_TASK_STATE", f"{name} is not allowed while the task is {state}.")


def _retain_preparation_provenance(task, report):
    differences = task.get("report", {}).get("resolved_differences")
    if differences:
        report["resolved_differences"] = differences
    return report


def update_constraints(connection, session, *, field, value, operation, user_message):
    """Apply one grounded requirement patch and invalidate the current recommendation."""
    task = session["task"]
    _require_task_state("update_constraints", task["state"])
    if field not in task["draft"] or field in ("parse_status", "missing_fields", "ambiguities"):
        raise ToolFailure("INVALID_FIELD", "This requirement field cannot be changed.")
    if field in ("customer", "product", "category") and operation not in ("unset", "undo"):
        mentioned = isinstance(value, str) and value.casefold() in user_message.casefold()
        registered = False
        if not mentioned and "registered" in user_message.casefold() and task["draft"].get("order_id"):
            order = get_order(connection, task["draft"]["order_id"])
            registered = bool(order and order[field] == value)
        if not mentioned and not registered:
            raise ToolFailure(
                "UNGROUNDED_CHANGE",
                "The value must appear in the current user message or match an explicitly requested registered order value.")
    context = build_context(connection, session)
    interpretation = TurnInterpretation(intent="modify_constraints", patch_operations=[{
        "op": operation, "field": field, "value": value,
        "evidence": {"message_sequence": context["current_sequence"], "quote": user_message}}])
    try:
        validate_interpretation(interpretation, user_message, context)
    except (ValueError, KeyError, TypeError) as error:
        raise ToolFailure(
            "UNGROUNDED_CHANGE",
            f"The requested change is not supported by the current user message: {error}") from None
    revised = apply_interpretation(task, interpretation, context["current_sequence"])
    revised["task_version"] += 1
    revised["state"] = "COLLECTING"
    revised["report"] = {}
    chat_repository.supersede_current(connection, session["session_id"])
    chat_repository.save_task(connection, revised)
    return {"draft": revised["draft"], "task_version": revised["task_version"],
            "state": revised["state"], "previous_recommendation_invalidated": True}


def check_requirements(connection, session, as_of):
    """Run preflight and update task readiness state."""
    task = session["task"]
    _require_task_state("check_requirements", task["state"])
    report, _, _, facts_hash = preflight(connection, task["draft"], as_of, task["issues"], task["sources"])
    _retain_preparation_provenance(task, report)
    task["report"] = report
    current_rec = chat_repository.latest_recommendation(connection, session["session_id"])
    recommendation_current = bool(
        current_rec and current_rec["status"] == "valid" and
        current_rec["facts_hash"] == facts_hash and
        current_rec["task_version"] == task["task_version"])
    task["state"] = (("RECOMMENDED" if recommendation_current else "READY")
                     if report["ready_for_planning"] else "BLOCKED")
    if not recommendation_current:
        chat_repository.supersede_current(connection, session["session_id"])
    chat_repository.save_task(connection, task)
    return {"state": task["state"], "report": report, "facts_hash": facts_hash}


def block_plan(connection, session, report, code, message):
    """Mark the task blocked after an invalid or stale plan attempt."""
    task = session["task"]
    task["state"] = "BLOCKED"
    task["report"] = report
    chat_repository.save_task(connection, task)
    chat_repository.supersede_current(connection, session["session_id"])
    raise ToolFailure(code, message)


def prepare_compute_plan(connection, session, as_of):
    """Validate task state and prepare an AllocationRequest for compute_plan."""
    task = session["task"]
    _require_task_state("compute_plan", task["state"])
    if task["state"] not in ("READY", "RECOMMENDED"):
        raise ToolFailure("INVALID_TASK_STATE",
                          "Run check_requirements successfully before computing a plan.")
    prepared = allocation.prepare_recommendation(
        connection, task["draft"], as_of, task["issues"], task["sources"])
    _retain_preparation_provenance(task, prepared["report"])
    return prepared


def finish_compute_plan(connection, session, prepared, result, as_of):
    """Check the plan, persist blockers, and return tool payload data."""
    task = session["task"]
    report, result, _, facts_hash, plan_hash = allocation.finish_recommendation(
        prepared, result, task["draft"], as_of)
    _retain_preparation_provenance(task, report)
    if not report["ready_for_recommendation"]:
        block_plan(connection, session, report, "PLAN_BLOCKED",
                   "The current constraints or business data do not yield a valid plan: " +
                   ", ".join(p["code"] for p in report["blocking_issues"]))
    return {"result": result, "report": report, "facts_hash": facts_hash, "plan_hash": plan_hash,
            "task_version": task["task_version"]}


def compute_plan(connection, session, as_of):
    """Prepare inputs, call allocator.allocate, then finish/check the plan."""
    from app.allocator import allocate
    prepared = prepare_compute_plan(connection, session, as_of)
    if prepared["request"] is None:
        block_plan(
            connection, session, prepared["report"], "PLAN_BLOCKED",
            "The current constraints or business data do not yield a valid plan: " +
            ", ".join(p["code"] for p in prepared["report"]["blocking_issues"]))
    result = allocate(prepared["request"])
    return finish_compute_plan(connection, session, prepared, result, as_of)


def save_recommendation(connection, session, as_of, plan):
    """Recompute under a write transaction and save a recommendation preview."""
    task = session["task"]
    _require_task_state("save_recommendation", task["state"])
    if task["state"] not in ("READY", "RECOMMENDED") or not plan:
        raise ToolFailure("PLAN_REQUIRED",
                          "Compute a valid plan in this run before saving a recommendation.")
    report, result, _, facts_hash, plan_hash = allocation.recommend(
        connection, task["draft"], as_of, task["issues"], task["sources"])
    _retain_preparation_provenance(task, report)
    if (not report["ready_for_recommendation"] or plan_hash != plan["plan_hash"] or
            facts_hash != plan["facts_hash"] or task["task_version"] != plan["task_version"]):
        block_plan(connection, session, report, "STALE_PLAN",
                   "Business facts, requirements, or the computed plan changed; recompute before saving.")
    rec = chat_repository.insert_recommendation(connection, session, result, facts_hash, plan_hash)
    task["state"] = "RECOMMENDED"
    task["report"] = report
    chat_repository.save_task(connection, task)
    return {"recommendation_id": rec["recommendation_id"], "task_version": rec["task_version"],
            "status": rec["status"], "result": rec["result"]}


def inspect_recommendation(connection, session):
    """Reconcile and return the latest saved recommendation for the session."""
    from app.services.chat import reconcile_recommendation
    reconcile_recommendation(connection, session)
    rec = chat_repository.latest_recommendation(connection, session["session_id"])
    if rec is None:
        raise ToolFailure("RECOMMENDATION_NOT_FOUND", "This session has no saved recommendation.")
    return rec
