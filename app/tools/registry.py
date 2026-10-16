"""Registered Tool objects, task permissions, and trusted invoke helpers."""
from pydantic import ValidationError

from app.schemas.tool import ToolFailure
from app.services.agent_operations import ALLOWED_TASK_STATES
from app.tools.allocation import compute_plan
from app.tools.conversation import ask_user, load_skill
from app.tools.orders import get_order
from app.tools.production import record_production_event
from app.tools.recommendations import inspect_recommendation, save_recommendation
from app.tools.requirements import check_requirements, update_constraints
from app.tools.scoring import (
    get_defect_score,
    get_estimated_completion_time,
    get_hybrid_score,
    get_lateness_score,
    score_workshop,
)
from app.tools.workshops import get_queue, list_workshops

TOOLS = {
    tool.name: tool
    for tool in (
        get_order,
        list_workshops,
        get_queue,
        score_workshop,
        get_estimated_completion_time,
        get_lateness_score,
        get_defect_score,
        get_hybrid_score,
        update_constraints,
        check_requirements,
        compute_plan,
        save_recommendation,
        inspect_recommendation,
        ask_user,
        load_skill,
        record_production_event,
    )
}

ALLOCATION_TOOLS = frozenset({
    "get_order", "list_workshops", "get_queue", "score_workshop",
    "get_estimated_completion_time", "get_lateness_score",
    "get_defect_score", "get_hybrid_score",
    "update_constraints", "check_requirements", "compute_plan",
    "save_recommendation", "inspect_recommendation", "ask_user",
})


def allowed_for_task(name: str, task_type: str) -> bool:
    """Code-owned authorization independent of Skill text."""
    return name in TOOLS and (task_type != "allocation" or name in ALLOCATION_TOOLS)


def invoke_tool(name, arguments, **configurable):
    """Invoke a registered Tool with trusted configurable context.

    Model-visible arguments only; connection/session/as_of live in config.
    """
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolFailure("UNKNOWN_TOOL", "The requested tool is not registered.")
    if not isinstance(arguments, dict):
        raise ToolFailure("INVALID_ARGUMENTS", "Tool arguments do not match the declared schema.")
    # LangChain may fill omitted optionals with None; keep the prior sparse contract.
    arguments = {key: value for key, value in arguments.items() if value is not None}
    try:
        return tool.invoke(arguments, config={"configurable": configurable})
    except ToolFailure:
        raise
    except ValidationError as error:
        raise ToolFailure("INVALID_ARGUMENTS", "Tool arguments do not match the declared schema.") from error
