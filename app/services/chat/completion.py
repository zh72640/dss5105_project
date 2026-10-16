"""Deterministic completion checks and reply verification against saved business results."""
import re

from app.schemas.agent import TaskResult
from app.services.allocation.contracts import saved_result

BASIC_ALLOCATION_POLICY = "allocation_v2"
ALLOCATION_STEPS = ("check_requirements", "compute_plan", "save_recommendation")


def allocation_execution_outcome(results):
    """Stop on a saved preview or failure; permit one stale-plan recovery."""
    stale = 0
    for index, item in enumerate(results):
        result = item["result"]
        if not result.get("ok"):
            error = result.get("error", {})
            if error.get("code") == "STALE_PLAN":
                stale += 1
                if stale == 1:
                    continue
            return True, error
        sequence_error = allocation_call_error(results[:index], item["name"])
        if sequence_error:
            return True, {"code": sequence_error[0], "message": sequence_error[1]}
        if item["name"] == "save_recommendation":
            return True, None
    return False, None


def allocation_call_error(results, name):
    """Runtime ordering policy; no Tool or model response can bypass it."""
    if name not in ALLOCATION_STEPS:
        return "TOOL_NOT_ALLOWED", "This tool is not allowed in the basic allocation workflow."
    steps = []
    for item in results:
        if item["result"].get("error", {}).get("code") == "STALE_PLAN":
            steps = []
        elif item["result"].get("ok") and item["name"] in ALLOCATION_STEPS:
            steps.append(item["name"])
    expected = ALLOCATION_STEPS[min(len(steps), len(ALLOCATION_STEPS) - 1)]
    if name != expected:
        return "INVALID_TOOL_SEQUENCE", "Call " + expected + " before continuing the allocation."
    return None


def evaluate_allocation(session, tool_results, pending_question=None, limit_reached=False,
                        *, execution_policy=None) -> TaskResult:
    task = session["task"]
    recommendation = session["recommendation"]
    issue = lambda code, message: {"code": code, "field": "workflow", "severity": "blocking", "question": message}
    if limit_reached:
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "failed",
                "result": None, "issues": [issue("EXECUTION_LIMIT", "The execution limit was reached. Retry the same request.")]}
    if execution_policy == BASIC_ALLOCATION_POLICY:
        complete, error = allocation_execution_outcome(tool_results)
        if not complete:
            error = next((item["result"]["error"] for item in reversed(tool_results)
                          if item["result"].get("error", {}).get("code") == "STALE_PLAN"),
                         {"code": "INCOMPLETE_RECOMMENDATION", "message": "No verified recommendation was saved."})
        if error:
            blocked = error.get("code") in {"SKILL_INPUT_INCOMPLETE", "SKILL_INPUT_STALE",
                "INVALID_ALLOCATION_INPUT", "PLAN_BLOCKED", "STALE_PLAN", "MULTI_WORKSHOP_UNSUPPORTED"}
            return {"task_id": task["task_id"], "task_type": "allocation",
                    "status": "blocked" if blocked else "failed", "result": None,
                    "issues": [issue(error.get("code", "ALLOCATION_FAILED"),
                                     error.get("message", "The allocation failed."))]}
    if pending_question:
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "waiting_user",
                "result": {"question": pending_question}, "issues": task["issues"]}
    saved = any(item["name"] == "save_recommendation" and item["result"].get("ok")
                for item in tool_results)
    if saved and recommendation and recommendation["status"] == "valid" and (
            recommendation["task_version"] == task["task_version"]):
        if execution_policy == BASIC_ALLOCATION_POLICY:
            try:
                saved_call = next(item for item in tool_results
                                  if item["name"] == "save_recommendation" and item["result"].get("ok"))
                if saved_call["result"]["data"]["recommendation_id"] != recommendation["recommendation_id"]:
                    raise ValueError("The saved tool result does not match the current recommendation.")
                payload = saved_result(recommendation)
            except (ValueError, KeyError, TypeError):
                return {"task_id": task["task_id"], "task_type": "allocation", "status": "failed",
                        "result": None, "issues": [issue("INVALID_RECOMMENDATION_RESULT",
                            "The saved recommendation result is incomplete or invalid.")]}
            return {"task_id": task["task_id"], "task_type": "allocation", "status": "waiting_user",
                    "result": payload, "issues": []}
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "waiting_user",
                "result": {"recommendation": recommendation}, "issues": []}
    if task["state"] == "BLOCKED" or task["issues"]:
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "blocked",
                "result": None, "issues": task["report"].get("blocking_issues") or task["issues"]}
    return {"task_id": task["task_id"], "task_type": "allocation", "status": "failed",
            "result": None, "issues": [issue("INCOMPLETE_RECOMMENDATION", "No verified recommendation was saved.")]}


def evaluate_compat(session, tool_results, pending_question=None) -> TaskResult:
    return {"task_id": session["task"]["task_id"], "task_type": "compat",
            "status": "waiting_user" if pending_question else "completed",
            "result": {"question": pending_question} if pending_question else None,
            "issues": []}


def _verified_reply(reply, state, task, recommendation):
    """Do not display an operation-success claim without its saved business result."""
    if re.search(r"\b(?:I (?:have )?|we (?:have )?)(?:committed|submitted|confirmed)\b|\b(?:has been|was|is now|successfully) (?:committed|submitted|confirmed)\b", reply, re.I):
        if task["state"] != "CONFIRMED" or not recommendation or recommendation["status"] != "confirmed":
            return "No allocation was committed. Confirm a valid recommendation card to submit it."
    if re.search(r"\b(?:I (?:have )?|we (?:have )?)recorded\b|\b(?:event|completion|cancellation|reassignment) (?:was|has been) recorded\b", reply, re.I):
        recorded = any(item["name"] == "record_production_event" and item["result"].get("ok")
                       for item in state.get("tool_results", []))
        if not recorded:
            return "No production event was recorded by this request. Check the order and retry with explicit details."
    return reply
