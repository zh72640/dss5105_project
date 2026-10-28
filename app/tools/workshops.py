"""Category 2: workshop fact Tools → app.db.workshop_repository."""
from dataclasses import asdict
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.db.workshop_repository import get_all
from app.schemas.tool import ToolFailure


@tool
def list_workshops(
    config: RunnableConfig,
    workshop_id: Annotated[str, Field(min_length=1)] | None = None,
) -> list:
    """
    Read current workshops and aged queue values for the business date.

    Args:
        workshop_id: Optional workshop ID filter. When omitted, return all workshops.
        config: Trusted runtime config (connection, as_of). Not model-supplied.

    Returns:
        list: Workshop rows with sorted capability categories and aged queues.

    Errors:
        WORKSHOP_NOT_FOUND when a filter ID matches no workshop.
    """
    connection = config["configurable"]["connection"]
    as_of = config["configurable"]["as_of"]
    workshops = get_all(connection, as_of)
    selected = [w for w in workshops if not workshop_id or w.workshop_id == workshop_id]
    if not selected:
        raise ToolFailure("WORKSHOP_NOT_FOUND", "No registered workshop has that ID.")
    return [{**asdict(w), "makes": sorted(w.makes)} for w in selected]


@tool
def get_queue(workshop_id: Annotated[str, Field(min_length=1)], config: RunnableConfig) -> dict:
    """
    Read one workshop's current aged queue in days for the business date.

    Queue aging is applied by the repository; this tool does not recompute it.

    Args:
        workshop_id: Exact registered workshop identifier.
        config: Trusted runtime config (connection, as_of). Not model-supplied.

    Returns:
        dict: workshop_id, queue_days, and as_of_date.

    Errors:
        WORKSHOP_NOT_FOUND when the workshop ID is unknown.
    """
    connection = config["configurable"]["connection"]
    as_of = config["configurable"]["as_of"]
    workshop = next((w for w in get_all(connection, as_of) if w.workshop_id == workshop_id), None)
    if workshop is None:
        raise ToolFailure("WORKSHOP_NOT_FOUND", "No registered workshop has that ID.")
    return {"workshop_id": workshop.workshop_id, "queue_days": workshop.queue_days,
            "as_of_date": as_of.isoformat()}
