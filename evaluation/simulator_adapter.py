"""Adapt the production planner to the unmodified official single-workshop API."""
from app.allocator.planner import plan
from app.schemas.parser_schema import OBJECTIVES, ParseResult
from app.tools.models import Workshop


def make_allocator(objective):
    if objective not in OBJECTIVES:
        raise ValueError("unknown objective")

    def allocate(batch, workshops, queues):
        candidates = [Workshop(w.workshop_id, w.name, w.capacity, w.lead_days, w.defect_rate,
                              w.cost, frozenset(w.makes), w.status, w.max_batch, queues[wid], w.notes)
                      for wid, w in workshops.items()]
        order = {"pieces": batch["pieces"], "category": batch["category"], "due_date": batch["due_date"].isoformat()}
        parsed = ParseResult(order_id=batch["order_id"], objective=objective, num_workshop_allowed=1, parse_status="ok")
        result = plan(order, candidates, parsed, objective, batch["sent_date"])
        if not result["success"] or len(result["allocation"]) != 1:
            raise ValueError("official simulator requires one eligible workshop: " + str(result["reason_codes"]))
        return result["allocation"][0]["workshop_id"]

    return allocate
