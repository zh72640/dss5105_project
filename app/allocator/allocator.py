"""Public allocate() entry: validate inputs then run deterministic planning."""
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.allocator.planner import plan
from app.schemas.parser_schema import OBJECTIVES


@dataclass(frozen=True)
class AllocationRequest:
    order: dict[str, Any]
    workshops: list
    as_of: date
    objective: str
    exclusion: list[str] = field(default_factory=list)
    preferred_workshop: str | None = None
    deadline_required: bool = False
    max_workshops: int = 1


def _validate(request: AllocationRequest) -> None:
    order = request.order
    if not isinstance(order, dict):
        raise ValueError("order must be a mapping")
    for key in ("pieces", "category", "due_date"):
        if key not in order:
            raise ValueError(f"order missing required field: {key}")
    if type(order["pieces"]) is not int or order["pieces"] <= 0:
        raise ValueError("order pieces must be a positive integer")
    try:
        date.fromisoformat(order["due_date"])
    except (TypeError, ValueError) as error:
        raise ValueError("order due_date must be an ISO date string") from error
    if type(request.as_of) is not date:
        raise ValueError("as_of must be a date")
    if request.objective not in OBJECTIVES:
        raise ValueError("objective is unsupported")
    if type(request.max_workshops) is not int or not 1 <= request.max_workshops <= 8:
        raise ValueError("max_workshops must be an integer from 1 to 8")
    if not isinstance(request.workshops, list):
        raise ValueError("workshops must be a list")
    if request.exclusion is not None and not isinstance(request.exclusion, list):
        raise ValueError("exclusion must be a list")
    if type(request.deadline_required) is not bool:
        raise ValueError("deadline_required must be a boolean")
    for workshop in request.workshops:
        if getattr(workshop, "capacity", 0) <= 0:
            raise ValueError(f"invalid capacity for workshop {getattr(workshop, 'workshop_id', '?')}")
        if getattr(workshop, "queue_days", 0) < 0:
            raise ValueError(f"invalid queue for workshop {getattr(workshop, 'workshop_id', '?')}")


def allocate(request: AllocationRequest) -> dict:
    """Compute one allocation plan. max_workshops>=2 enables multi-workshop enumeration."""
    _validate(request)
    return plan(
        request.order,
        request.workshops,
        objective=request.objective,
        as_of=request.as_of,
        max_workshops=request.max_workshops,
        exclusion=list(request.exclusion or []),
        preferred_workshop=request.preferred_workshop,
        deadline_required=request.deadline_required,
    )
