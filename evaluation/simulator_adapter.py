"""Adapt the production planner to the unmodified official single-workshop API."""
from app.allocator import AllocationRequest, allocate
from app.schemas.parser_schema import OBJECTIVES
from app.schemas.business import Workshop


def make_allocator(objective):
    if objective not in OBJECTIVES:
        raise ValueError("unknown objective")

    def allocate_one(batch, workshops, queues):
        candidates = [Workshop(w.workshop_id, w.name, w.capacity, w.lead_days, w.defect_rate,
                              w.cost, frozenset(w.makes), w.status, w.max_batch, queues[wid], w.notes)
                      for wid, w in workshops.items()]
        order = {"pieces": batch["pieces"], "category": batch["category"], "due_date": batch["due_date"].isoformat()}
        result = allocate(AllocationRequest(
            order=order, workshops=candidates, as_of=batch["sent_date"], objective=objective,
            max_workshops=1))
        if not result["success"] or len(result["allocation"]) != 1:
            raise ValueError("official simulator requires one eligible workshop: " + str(result["reason_codes"]))
        return result["allocation"][0]["workshop_id"]

    return allocate_one
