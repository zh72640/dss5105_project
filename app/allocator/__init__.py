"""Deterministic allocation math. No Agent, DB, or LLM dependencies."""
from app.allocator.allocator import AllocationRequest, allocate
from app.allocator.eligibility import exclusion_reason
from app.allocator.scoring import (
    get_defect_score,
    get_estimated_completion_time,
    get_hybrid_score,
    get_lateness_score,
)

__all__ = [
    "AllocationRequest",
    "allocate",
    "exclusion_reason",
    "get_defect_score",
    "get_estimated_completion_time",
    "get_hybrid_score",
    "get_lateness_score",
]
