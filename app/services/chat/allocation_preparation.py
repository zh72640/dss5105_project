"""Fixed deterministic preparation for the LLM Allocation subgraph."""
from copy import deepcopy

from app.db import chat_repository, preparation_repository
from app.db.database import Database
from app.db.order_repository import get_order
from app.services.allocation.preflight import preflight
from app.services.chat.constraint_patches import apply_interpretation
from app.services.allocation.contracts import inspect_input, single_workshop_issues

FACT_FIELDS = ("customer", "product", "category", "pieces", "order_date", "due_date")


def prepare(*, db_path, session_id, owner, request_id, interpretation, as_of, sequence):
    """Apply grounded extraction once, then check database facts without tools."""
    with Database(db_path) as db:
        with db.transaction() as connection:
            cached = preparation_repository.existing(connection, request_id)
            if cached is not None:
                return cached
            session = chat_repository.snapshot(connection, session_id, owner)
            if session is None or session["status"] != "OPEN":
                raise ValueError("SESSION_NOT_FOUND")
            task = deepcopy(session["task"])
            if task["state"] in ("CONFIRMED", "CANCELLED"):
                return {"ready": False, "task": task, "issues": [{
                    "code": "TASK_CLOSED", "field": "task", "severity": "blocking",
                    "question": "Create a new request for another allocation."}]}
            if interpretation.patch_operations or interpretation.ambiguity_reason or interpretation.unsupported_constraints:
                task = apply_interpretation(task, interpretation, sequence)
                task["task_version"] += 1
                chat_repository.supersede_current(connection, session_id)
            differences = []
            order_id = task["draft"].get("order_id")
            order = get_order(connection, order_id) if order_id else None
            if order:
                for field in FACT_FIELDS:
                    supplied = task["draft"].get(field)
                    recorded = order[field]
                    if supplied is not None and str(supplied).casefold() != str(recorded).casefold():
                        differences.append({"field": field, "supplied": supplied, "recorded": recorded})
                    task["draft"][field] = recorded
            report, _, _, facts_hash = preflight(connection, task["draft"], as_of,
                                                task["issues"], task["sources"])
            skill_input, input_issues = inspect_input(task["draft"])
            input_issues += single_workshop_issues(task["draft"])
            report["blocking_issues"] = input_issues + report["blocking_issues"]
            report["ready_for_planning"] = not report["blocking_issues"]
            report["resolved_differences"] = differences
            task["report"] = report
            current = chat_repository.latest_recommendation(connection, session_id)
            current_valid = bool(current and current["status"] == "valid" and
                                 current["task_version"] == task["task_version"] and
                                 current["facts_hash"] == facts_hash)
            task["state"] = ("RECOMMENDED" if current_valid else "READY") if report["ready_for_planning"] else "BLOCKED"
            chat_repository.save_task(connection, task)
            result = {"ready": report["ready_for_planning"], "task": task,
                      "issues": report["blocking_issues"], "facts_hash": facts_hash,
                      "resolved_differences": differences, "skill_input": skill_input}
            preparation_repository.record(connection, session_id, request_id, result)
            return result
