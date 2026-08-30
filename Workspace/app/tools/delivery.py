from datetime import date, timedelta
from app.schemas import CandidateMetrics
from .eligibility import exclusion_reason
from .models import Workshop


def estimate_candidate(workshop: Workshop, category: str, pieces: int, required_date: str,
                       excluded: list[str], today: date = date(2026, 4, 1)) -> CandidateMetrics:
    reason = exclusion_reason(workshop, category, pieces, excluded)
    processing = pieces / workshop.capacity
    turnaround = workshop.queue_days + processing + workshop.lead_days
    delivery = today + timedelta(days=round(turnaround))
    return CandidateMetrics(workshop.workshop_id, workshop.name, reason is None, reason,
        workshop.queue_days, processing, workshop.lead_days, turnaround, pieces * workshop.cost,
        workshop.defect_rate, delivery.isoformat(), delivery <= date.fromisoformat(required_date))

