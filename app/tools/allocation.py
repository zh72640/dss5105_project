"""Category 1: plan computation Tool → service wrapper that calls allocator.allocate."""
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.services.chat import operations as agent_operations


@tool
def compute_plan(config: RunnableConfig) -> dict:
    """
    Compute and verify an integer allocation plan for a READY task.

    Does not save a recommendation or write production allocation. Requires
    check_requirements to have succeeded. Uses allocator.allocate with
    sources-gated max_workshops from the allocation service.

    Args:
        config: Trusted runtime config (connection, session, as_of). Not model-supplied.

    Returns:
        dict: result, report, facts_hash, plan_hash, and task_version.

    Errors:
        INVALID_TASK_STATE, PLAN_BLOCKED, SKILL_INPUT_INCOMPLETE, SKILL_INPUT_STALE,
        INVALID_ALLOCATION_INPUT, MULTI_WORKSHOP_UNSUPPORTED.
    """
    cfg = config["configurable"]
    return agent_operations.compute_plan(
        cfg["connection"], cfg["session"], cfg["as_of"], allocation_input=cfg.get("allocation_input"))
