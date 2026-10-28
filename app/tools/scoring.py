"""Category 1: single-workshop scoring Tools → app.allocator.scoring."""
from datetime import date
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.allocator.scoring import (
    get_defect_score as defect_score_fn,
    get_estimated_completion_time as eta_fn,
    get_hybrid_score as hybrid_score_fn,
    get_lateness_score as lateness_score_fn,
    score_workshop as score_workshop_metrics,
)
from app.db.order_repository import get_order
from app.db.workshop_repository import get_all
from app.schemas.business import Workshop
from app.schemas.tool import ToolFailure


def _load_score_inputs(
    workshop_id: str,
    order_id: str,
    config: RunnableConfig,
    pieces: int | None,
) -> tuple[Workshop, dict, dict, dict, date]:
    """Resolve workshop/order facts and build batch/queues for allocator formulas."""
    connection = config["configurable"]["connection"]
    as_of = config["configurable"]["as_of"]
    session = config["configurable"]["session"]
    workshop = next((w for w in get_all(connection, as_of) if w.workshop_id == workshop_id), None)
    if workshop is None:
        raise ToolFailure("WORKSHOP_NOT_FOUND", "No registered workshop has that ID.")
    order = get_order(connection, order_id)
    if order is None:
        raise ToolFailure("ORDER_NOT_FOUND", "No registered order has that ID.")
    batch_pieces = pieces if pieces is not None else order["pieces"] - order["completed_pieces"]
    if type(batch_pieces) is not int or batch_pieces <= 0 or workshop.capacity <= 0:
        raise ToolFailure(
            "INVALID_QUANTITY",
            "A positive integer batch and positive workshop capacity are required.")
    batch = {
        "pieces": batch_pieces,
        "due_date": date.fromisoformat(order["due_date"]),
        "sent_date": as_of,
    }
    queues = {workshop.workshop_id: workshop.queue_days}
    return workshop, order, batch, queues, as_of


@tool
def score_workshop(
    workshop_id: Annotated[str, Field(min_length=1)],
    order_id: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    pieces: Annotated[int, Field(ge=1)] | None = None,
) -> dict:
    """
    Score one registered order against one workshop using original formulas.

    Use for order-specific single-workshop comparisons. Not the planner weighted
    hybrid objective. Loads workshop/order facts, then calls allocator scoring.

    Args:
        workshop_id: Exact registered workshop identifier.
        order_id: Exact registered order identifier.
        pieces: Optional positive batch size; defaults to remaining order pieces.
        config: Trusted runtime config (connection, as_of, session). Not model-supplied.

    Returns:
        dict: ETA, lateness, defect, original hybrid, eligibility rejection, and inputs.

    Errors:
        WORKSHOP_NOT_FOUND, ORDER_NOT_FOUND, INVALID_QUANTITY.
    """
    workshop, order, _batch, _queues, as_of = _load_score_inputs(
        workshop_id, order_id, config, pieces)
    session = config["configurable"]["session"]
    try:
        return score_workshop_metrics(
            workshop, order, as_of,
            pieces=pieces,
            exclusion=session["task"]["draft"].get("exclusion") or [])
    except ValueError as error:
        if str(error) == "INVALID_QUANTITY":
            raise ToolFailure(
                "INVALID_QUANTITY",
                "A positive integer batch and positive workshop capacity are required.") from error
        raise


@tool
def get_estimated_completion_time(
    workshop_id: Annotated[str, Field(min_length=1)],
    order_id: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    pieces: Annotated[int, Field(ge=1)] | None = None,
) -> float:
    """
    Estimated completion days for one order batch at one workshop.

    Args:
        workshop_id: Exact registered workshop identifier.
        order_id: Exact registered order identifier.
        pieces: Optional positive batch size; defaults to remaining order pieces.
        config: Trusted runtime config (connection, as_of, session). Not model-supplied.

    Returns:
        float: Estimated completion time in days (processing + lead + queue).

    Errors:
        WORKSHOP_NOT_FOUND, ORDER_NOT_FOUND, INVALID_QUANTITY.
    """
    workshop, _order, batch, queues, _as_of = _load_score_inputs(
        workshop_id, order_id, config, pieces)
    return eta_fn(workshop, batch, queues)


@tool
def get_lateness_score(
    workshop_id: Annotated[str, Field(min_length=1)],
    order_id: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    pieces: Annotated[int, Field(ge=1)] | None = None,
) -> float:
    """
    Lateness score for one order batch at one workshop.

    Negative values mean completion before the deadline. Inactive workshops
    score 10000.

    Args:
        workshop_id: Exact registered workshop identifier.
        order_id: Exact registered order identifier.
        pieces: Optional positive batch size; defaults to remaining order pieces.
        config: Trusted runtime config (connection, as_of, session). Not model-supplied.

    Returns:
        float: ETA minus allowed days, or 10000 if inactive.

    Errors:
        WORKSHOP_NOT_FOUND, ORDER_NOT_FOUND, INVALID_QUANTITY.
    """
    workshop, _order, batch, queues, _as_of = _load_score_inputs(
        workshop_id, order_id, config, pieces)
    return lateness_score_fn(workshop, batch, queues)


@tool
def get_defect_score(
    workshop_id: Annotated[str, Field(min_length=1)],
    order_id: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    pieces: Annotated[int, Field(ge=1)] | None = None,
) -> float:
    """
    Defect score for one order batch at one workshop.

    Active workshops return defect rate; inactive workshops score 10000.

    Args:
        workshop_id: Exact registered workshop identifier.
        order_id: Exact registered order identifier.
        pieces: Optional positive batch size; defaults to remaining order pieces.
        config: Trusted runtime config (connection, as_of, session). Not model-supplied.

    Returns:
        float: Workshop defect rate, or 10000 if inactive.

    Errors:
        WORKSHOP_NOT_FOUND, ORDER_NOT_FOUND, INVALID_QUANTITY.
    """
    workshop, _order, batch, _queues, _as_of = _load_score_inputs(
        workshop_id, order_id, config, pieces)
    return defect_score_fn(workshop, batch)


@tool
def get_hybrid_score(
    workshop_id: Annotated[str, Field(min_length=1)],
    order_id: Annotated[str, Field(min_length=1)],
    config: RunnableConfig,
    pieces: Annotated[int, Field(ge=1)] | None = None,
) -> float:
    """
    Original deadline-gated hybrid score for one order at one workshop.

    Returns defect rate when on time; otherwise 10000. Not the planner's
    weighted hybrid objective.

    Args:
        workshop_id: Exact registered workshop identifier.
        order_id: Exact registered order identifier.
        pieces: Optional positive batch size; defaults to remaining order pieces.
        config: Trusted runtime config (connection, as_of, session). Not model-supplied.

    Returns:
        float: Deadline-gated defect rate, or 10000 when late/inactive.

    Errors:
        WORKSHOP_NOT_FOUND, ORDER_NOT_FOUND, INVALID_QUANTITY.
    """
    workshop, _order, batch, queues, _as_of = _load_score_inputs(
        workshop_id, order_id, config, pieces)
    return hybrid_score_fn(workshop, batch, queues)
