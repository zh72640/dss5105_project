"""Format saved allocation results for deterministic desk and audit summaries."""
from .templates import OBJECTIVES, TEXT


def allocation_reply(result, order_id=None, *, committed=False):
    parts = result.get("allocation", [])
    if not result.get("success") or not parts:
        return result.get("message", TEXT["no_allocation"])
    total = sum(part["pieces"] for part in parts)
    assignments = "; ".join(TEXT["assignment"].format(**part) for part in parts)
    prefix = TEXT["approved"] if committed else TEXT["proposed"]
    text = TEXT["allocation_intro"].format(prefix=prefix, order=order_id or TEXT["this_order"], total=total)
    text += (TEXT["assigned"] if committed else TEXT["recommend"]) + assignments + ". "
    if result.get("estimated_delivery_date"):
        text += TEXT["completion"].format(date=result["estimated_delivery_date"])
    if result.get("estimated_cost") is not None:
        text += TEXT["cost"].format(cost=result["estimated_cost"])
    text += TEXT["objective"].format(objective=OBJECTIVES.get(result.get("objective"), TEXT["chosen_objective"]))
    if "ESTIMATED_DEADLINE_MISS" in result.get("warnings", []):
        text += TEXT["lateness"]
    if not committed:
        text += TEXT["accept"]
    return text
