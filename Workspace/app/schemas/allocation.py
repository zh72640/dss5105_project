from dataclasses import asdict, dataclass, field
from enum import Enum
from .candidate import CandidateMetrics


class DecisionStatus(str, Enum):
    READY = "READY"
    ALLOCATE = "ALLOCATE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"
    DECLINE = "DECLINE"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AllocationResult:
    request_id: str | None
    decision_status: DecisionStatus
    recommended_workshop_id: str | None = None
    recommended_workshop_name: str | None = None
    candidate_ranking: list[CandidateMetrics] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    objective: str | None = None
    warnings: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        value = asdict(self)
        value["decision_status"] = self.decision_status.value
        return value

