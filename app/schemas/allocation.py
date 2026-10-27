"""Typed handoff and saved result contracts for the basic allocation workflow."""
from datetime import date
from typing import Annotated

from pydantic import Field, FiniteFloat, field_validator

from app.schemas.api import Input


class AllocationFields(Input):
    """Missing fields are accepted here and checked after database enrichment."""
    order_id: str | None = None
    product: str | None = None
    pieces: Annotated[int, Field(gt=0)] | None = None
    due_date: str | None = None

    @field_validator("order_id", "product", "due_date", mode="before")
    @classmethod
    def empty_is_missing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class AllocationSkillInput(AllocationFields):
    order_id: Annotated[str, Field(min_length=1)]
    product: Annotated[str, Field(min_length=1)]
    pieces: Annotated[int, Field(gt=0)]
    due_date: str


class AllocationCandidateEvidence(Input):
    workshop_id: str
    workshop_name: str
    score: FiniteFloat
    estimated_days: FiniteFloat
    estimated_cost: FiniteFloat
    expected_defect_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    scoring_components: dict[str, FiniteFloat] = Field(default_factory=dict)


class AllocationExplanationEvidence(Input):
    method: str
    score_formula: str
    comparison_scope: str
    selection_reason: str
    selected_score: FiniteFloat
    queue_days: FiniteFloat
    processing_days: FiniteFloat
    transport_days: FiniteFloat
    eligible_workshops: list[str]
    rejected_workshops: dict[str, str]
    required_sole_workshop: str | None = None
    deadline_required: bool
    candidates: list[AllocationCandidateEvidence]


class AllocationRecommendationResult(AllocationSkillInput):
    recommendation_id: str
    task_version: Annotated[int, Field(ge=0)]
    workshop_id: str
    workshop_name: str
    allocated_pieces: Annotated[int, Field(gt=0)]
    estimated_delivery_date: str
    delay_days: int
    expected_defect_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    estimated_cost: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    objective: str
    warnings: list[str]
    explanation_evidence: AllocationExplanationEvidence | None = None

    @field_validator("estimated_delivery_date")
    @classmethod
    def valid_delivery_date(cls, value):
        date.fromisoformat(value)
        return value
