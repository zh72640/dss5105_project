"""Workflow contracts shared by the main graph and business subgraphs."""
from typing import Any, Literal, TypedDict

TaskStatus = Literal["completed", "waiting_user", "blocked", "failed"]


class TaskResult(TypedDict):
    task_id: str
    task_type: str
    status: TaskStatus
    result: dict[str, Any] | None
    issues: list[dict[str, Any]]


class ExplanationInput(TypedDict):
    """Runtime-owned business provenance and the verified result to explain."""
    source_node: str
    task_result: TaskResult


class ExplanationResult(TypedDict):
    """Presentation text; it never replaces the business result."""
    text: str
