"""Category 4: production-event Tool → app.services.production.agent_events."""
from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.services.production import agent_events as agent_production


@tool
def record_production_event(
    action: Literal["complete", "cancel", "lapse", "reassign"],
    order_id: Annotated[str, Field(min_length=1)],
    expected_version: Annotated[int, Field(ge=0)],
    reason: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    workshop_id: Annotated[str, Field(min_length=1)] | None = None,
    pieces: Annotated[int, Field(ge=1)] | None = None,
    objective: Literal["min_delay", "min_cost", "min_defects", "hybrid", "weighted_hybrid"] | None = None,
    exclusion: list[str] | None = None,
    max_workshops: Annotated[int, Field(ge=1)] | None = None,
    preferred_workshop: Annotated[str, Field(min_length=1)] | None = None,
    deadline_required: bool | None = None,
) -> dict:
    """
    Record an explicitly requested, audited production event.

    The authenticated account is the actor. The server builds an idempotent event ID
    from the invocation key. The current user message must ground action-specific fields.

    Args:
        action: complete, cancel, lapse, or reassign.
        order_id: Target order identifier.
        expected_version: Optimistic concurrency version.
        reason: Audit reason grounded in the user message.
        workshop_id / pieces: Required for complete; forbidden otherwise.
        objective / exclusion / max_workshops / preferred_workshop / deadline_required:
            Optional reassign constraints when grounded in the user message.
        config: Trusted runtime config (owner, db_path, as_of, user_message, invocation_key).

    Returns:
        dict: {ok, data} envelope; on business refusal also includes error.

    Errors:
        EVENT_NOT_AUTHORIZED, INVALID_ARGUMENTS, plus lifecycle reason codes in the envelope.
    """
    cfg = config["configurable"]
    return agent_production.record_production_event(
        user_message=cfg["user_message"], owner=cfg["owner"], db_path=cfg["db_path"],
        as_of=cfg["as_of"], invocation_key=cfg["invocation_key"],
        action=action, order_id=order_id, expected_version=expected_version, reason=reason,
        workshop_id=workshop_id, pieces=pieces, objective=objective, exclusion=exclusion,
        max_workshops=max_workshops, preferred_workshop=preferred_workshop,
        deadline_required=deadline_required)
