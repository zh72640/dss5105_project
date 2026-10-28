"""Category 2: order fact Tool → app.db.order_repository."""
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.db.order_repository import get_order as load_order
from app.schemas.tool import ToolFailure


@tool
def get_order(order_id: Annotated[str, Field(min_length=1)], config: RunnableConfig) -> dict:
    """
    Read a registered order and its current production state.

    Args:
        order_id: Exact registered order identifier.
        config: Trusted runtime config (connection). Not model-supplied.

    Returns:
        dict: Registered order fields plus remaining_pieces.

    Errors:
        ORDER_NOT_FOUND when the ID is not registered.
    """
    connection = config["configurable"]["connection"]
    order = load_order(connection, order_id)
    if order is None:
        raise ToolFailure("ORDER_NOT_FOUND", "No registered order has that ID.")
    return {**order, "remaining_pieces": order["pieces"] - order["completed_pieces"]}
