from datetime import date

from app.allocator.eligibility import exclusion_reason
from app.schemas.business import Workshop


def get_estimated_completion_time(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """Processing days + lead days + queue days for the batch."""
    eta = batch["pieces"] / workshop.capacity + workshop.lead_days + queues[workshop.workshop_id]
    return eta


def get_lateness_score(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """ETA minus allowed days; 10000 when the workshop is inactive."""
    eta = get_estimated_completion_time(workshop, batch, queues)
    allowed_days = (batch["due_date"] - batch["sent_date"]).days
    lateness_score = eta - allowed_days if workshop.status == "ACTIVE" else 10000
    return lateness_score


def get_defect_score(
    workshop: Workshop,
    batch: dict
) -> float:
    """Workshop defect rate when active; 10000 otherwise."""
    return workshop.defect_rate if workshop.status == "ACTIVE" else 10000


def get_hybrid_score(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """Deadline-gated defect rate; 10000 when late or inactive."""
    lateness_score = get_lateness_score(workshop, batch, queues)
    defect_score = get_defect_score(workshop, batch)

    hybrid_score = defect_score if lateness_score <= 0 else 10000
    return hybrid_score


def score_workshop(
    workshop: Workshop,
    order: dict,
    as_of: date,
    *,
    pieces: int | None = None,
    exclusion: list[str] | None = None,
) -> dict:
    batch_pieces = pieces if pieces is not None else order["pieces"] - order["completed_pieces"]
    if type(batch_pieces) is not int or batch_pieces <= 0 or workshop.capacity <= 0:
        raise ValueError("INVALID_QUANTITY")
    batch = {
        "pieces": batch_pieces,
        "due_date": date.fromisoformat(order["due_date"]),
        "sent_date": as_of,
    }
    queues = {workshop.workshop_id: workshop.queue_days}
    return {
        "workshop_id": workshop.workshop_id,
        "order_id": order["order_id"],
        "pieces": batch_pieces,
        "sent_date": as_of.isoformat(),
        "queue_days": workshop.queue_days,
        "estimated_completion_days": get_estimated_completion_time(workshop, batch, queues),
        "lateness_score_days": get_lateness_score(workshop, batch, queues),
        "defect_score": get_defect_score(workshop, batch),
        "original_hybrid_score": get_hybrid_score(workshop, batch, queues),
        "eligibility_rejection": exclusion_reason(
            workshop, order["category"], batch_pieces, list(exclusion or [])),
        "score_semantics": (
            "Original single-workshop formulas; original hybrid returns defect rate only if on time, "
            "otherwise 10000. The planner uses a different weighted objective."),
    }
