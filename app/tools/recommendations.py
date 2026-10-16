"""Category 4: recommendation Tools → app.services.chat.operations."""
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.services.chat import operations as agent_operations


@tool
def save_recommendation(config: RunnableConfig) -> dict:
    """
    Save the plan computed in this run after checking fresh facts and plan hash.

    Does not write production allocations. Requires a valid plan from compute_plan
    in the current graph run.

    Args:
        config: Trusted runtime config (connection, session, as_of, plan).

    Returns:
        dict: recommendation_id, task_version, status, result.

    Errors:
        INVALID_TASK_STATE, PLAN_REQUIRED, STALE_PLAN, SKILL_INPUT_INCOMPLETE,
        SKILL_INPUT_STALE, INVALID_ALLOCATION_INPUT, MULTI_WORKSHOP_UNSUPPORTED.
    """
    cfg = config["configurable"]
    return agent_operations.save_recommendation(
        cfg["connection"], cfg["session"], cfg["as_of"], cfg.get("plan"),
        allocation_input=cfg.get("allocation_input"))


@tool
def inspect_recommendation(config: RunnableConfig) -> dict:
    """
    Read the saved recommendation and current validity from the database.

    Reconciles stale cards against current business facts before returning.

    Args:
        config: Trusted runtime config (connection, session).

    Returns:
        dict: Latest recommendation row for the session.

    Errors:
        RECOMMENDATION_NOT_FOUND.
    """
    cfg = config["configurable"]
    return agent_operations.inspect_recommendation(cfg["connection"], cfg["session"])
