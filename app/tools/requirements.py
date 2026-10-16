"""Category 4: requirement Tools → app.services.agent_operations."""
from typing import Annotated, Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.services import agent_operations


@tool
def update_constraints(
    field: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    value: Any = None,
    operation: Literal["set", "unset", "add", "remove", "undo"] = "set",
) -> dict:
    """
    Apply one requirement grounded in the current user message.

    Supersedes an old recommendation. Do not invent fields missing from the draft.

    Args:
        field: Draft requirement field name.
        value: New value for set/add/remove operations.
        operation: set, unset, add, remove, or undo.
        config: Trusted runtime config (connection, session, user_message).

    Returns:
        dict: draft, task_version, state, previous_recommendation_invalidated.

    Errors:
        INVALID_TASK_STATE, INVALID_FIELD, UNGROUNDED_CHANGE.
    """
    cfg = config["configurable"]
    return agent_operations.update_constraints(
        cfg["connection"], cfg["session"],
        field=field, value=value, operation=operation,
        user_message=cfg["user_message"])


@tool
def check_requirements(config: RunnableConfig) -> dict:
    """
    Run authoritative preflight and update task readiness state.

    Call after constraints are collected. Does not compute or save a plan.

    Args:
        config: Trusted runtime config (connection, session, as_of).

    Returns:
        dict: state, report, facts_hash.

    Errors:
        INVALID_TASK_STATE.
    """
    cfg = config["configurable"]
    return agent_operations.check_requirements(cfg["connection"], cfg["session"], cfg["as_of"])
