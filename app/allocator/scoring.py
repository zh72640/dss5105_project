from dataclasses import replace
from app.schemas import CandidateMetrics


def score(candidate: CandidateMetrics, objective: str) -> float:
    if objective == "min_defects":
        return candidate.defect_rate
    if objective == "min_cost":
        return candidate.estimated_cost
    if objective == "hybrid":
        return 0.6 * candidate.turnaround_days + 0.4 * candidate.defect_rate * 100
    return candidate.turnaround_days


def with_score(candidate: CandidateMetrics, objective: str) -> CandidateMetrics:
    return replace(candidate, score=score(candidate, objective))

