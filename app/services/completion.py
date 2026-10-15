"""Business completion checks independent of model wording."""
from app.schemas.agent import TaskResult


def evaluate_allocation(session, tool_results, pending_question=None, limit_reached=False) -> TaskResult:
    task = session["task"]
    recommendation = session["recommendation"]
    issue = lambda code, message: {"code": code, "field": "workflow", "severity": "blocking", "question": message}
    if limit_reached:
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "failed",
                "result": None, "issues": [issue("EXECUTION_LIMIT", "The execution limit was reached. Retry the same request.")]}
    if pending_question:
        return {"task_id": task["task_id"], "task_type": "allocation", "status": "waiting_user",
                "result": {"question": pending_question}, "issues": task["issues"]}
    saved = any(item["name"] == "save_recommendation" and item["result"].get("ok")
                for item in tool_results)
    if saved and recommendation and recommendation["status"] == "valid" and (
            recommendation["task_version"] == task["task_version"]):
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
