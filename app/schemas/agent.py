"""Workflow contracts shared by the main graph and business subgraphs."""
from typing import Any, Literal, TypedDict

TaskStatus = Literal["completed", "waiting_user", "blocked", "failed"]


class TaskResult(TypedDict):
    task_id: str
    task_type: str
    status: TaskStatus
    result: dict[str, Any] | None
    issues: list[dict[str, Any]]
