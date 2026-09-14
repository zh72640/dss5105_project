from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CandidateMetrics:
    workshop_id: str
    workshop_name: str
    eligible: bool
    exclusion_reason: str | None
    queue_days: float
    processing_days: float
    transport_days: int
    turnaround_days: float
    estimated_cost: float
    defect_rate: float
    estimated_delivery_date: str
    deadline_met: bool
    score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

