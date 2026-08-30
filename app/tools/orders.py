from app.schemas import StructuredRequest
from .data import load_orders
from .models import Order


def resolve_order(request: StructuredRequest) -> tuple[Order | None, str | None]:
    orders = load_orders()
    if request.order_id:
        order = orders.get(request.order_id)
        return (order, None) if order else (None, f"Order {request.order_id} is not in the dataset")
    matches = [o for o in orders.values() if not request.customer or o.customer.casefold() == request.customer.casefold()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"{len(matches)} orders match {request.customer or 'the request'}"
    return None, "No matching order was found"

