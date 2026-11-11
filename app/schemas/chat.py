"""Chat v2 inputs and context-aware interpretation, independent of parser_v1."""
from typing import Any, Literal
from pydantic import Field, model_validator
from app.schemas.api import Input, Output, Identifier, Version, Objective
from app.schemas.allocation import AllocationRecommendationResult
from app.schemas.order_registration import RegistrationDecision

Intent = Literal['new_request', 'allocate_request', 'answer_clarification', 'modify_constraints',
    'request_alternatives', 'select_workshop',
    'undo_change', 'query_order', 'query_workshop', 'explain_recommendation', 'reject_recommendation',
    'confirm_allocation', 'cancel_task', 'help_or_chat', 'unsupported_or_ambiguous']


class ChatCreateInput(Input):
    request_id: Identifier
    message: str = Field(default='', max_length=10000)
    objective: Objective = 'min_delay'
    mode: Literal['offline', 'llm'] | None = None
    model_key: Identifier | None = None


class ChatTurnInput(Input):
    request_id: Identifier
    expected_version: Version
    action: Literal['message', 'new_request', 'confirm', 'archive', 'order_decision'] = 'message'
    message: str = Field(default='', max_length=10000)
    recommendation_id: Identifier | None = None
    order_decision: RegistrationDecision | None = None

    @model_validator(mode='after')
    def confirmation_target(self):
        if self.action=='confirm' and not self.recommendation_id:
            raise ValueError('confirmation requires recommendation_id')
        if (self.action == 'order_decision') != (self.order_decision is not None):
            raise ValueError('order_decision action requires its decision payload exclusively')
        if self.action == 'order_decision' and (self.message or self.recommendation_id):
            raise ValueError('Send revisions separately before deciding on an order')
        return self


class ChatEndRequestInput(Input):
    expected_version: Version


PatchField = Literal['order_id', 'customer', 'product', 'category', 'pieces',
    'order_date', 'due_date', 'objective', 'exclusion', 'num_workshop_allowed',
    'preferred_workshop', 'deadline_required']


class AllocationPatch(Input):
    """Current-message extraction; Runtime supplies the evidence sequence."""
    op: Literal['set', 'unset', 'add', 'remove', 'undo']
    field: PatchField
    value: Any = None
    quote: str = Field(min_length=1, max_length=10000)


UnsupportedAllocationConstraint = Literal['unsupported_constraint', 'soft_workshop_preference', 'optional_split']


class AlternativeAcceptance(Input):
    """Current-message authorization to apply one saved alternative's changes."""
    alternative_id: str | None = Field(default=None, min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=10000)
    resolved_reference_issue_ids: list[str] = Field(default_factory=list, max_length=24)


class AllocationExtraction(Input):
    intent: Intent
    accept_alternative: AlternativeAcceptance | None = None
    patch_operations: list[AllocationPatch] = Field(default_factory=list)
    ambiguity_reason: str | None = None
    unsupported_constraints: list[UnsupportedAllocationConstraint] = Field(default_factory=list)
    answered_question_ids: list[Literal['unsupported_constraint', 'AMBIGUOUS_MESSAGE', 'soft_workshop_preference']] = Field(default_factory=list)

    def with_evidence(self, sequence):
        return TurnInterpretation(intent=self.intent, accept_alternative=self.accept_alternative, ambiguity_reason=self.ambiguity_reason,
            unsupported_constraints=self.unsupported_constraints,
            answered_question_ids=self.answered_question_ids, patch_operations=[{
                'op': patch.op, 'field': patch.field, 'value': patch.value,
                'evidence': {'message_sequence': sequence, 'quote': patch.quote}}
                for patch in self.patch_operations])


class Evidence(Input):
    message_sequence: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=10000)


class PatchOperation(Input):
    op: Literal['set', 'unset', 'add', 'remove', 'undo']
    field: str
    value: Any = None
    evidence: Evidence


class TurnInterpretation(Input):
    intent: Intent
    accept_alternative: AlternativeAcceptance | None = None
    candidate_intents: list[str] = Field(default_factory=list)
    ambiguity_reason: str | None = None
    # Derived from current-message evidence by intake, never supplied by the LLM.
    due_date_pending: bool = False
    recommend_without_due_date: bool = False
    allocation_notices: list[dict[str, Any]] = Field(default_factory=list)
    referenced_order_id: str | None = None
    referenced_recommendation_id: str | None = None
    patch_operations: list[PatchOperation] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    answered_question_ids: list[str] = Field(default_factory=list)


class AllocationResponseBody(Input):
    """Allocation-specific content assembled before the HTTP transaction envelope."""
    type: Literal['allocation'] = 'allocation'
    explanation: str = Field(min_length=1)
    allocation: AllocationRecommendationResult | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    recommendation_id: str | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class ChatOutput(Output):
    session_id: str
    session_version: int
    assistant_message: dict[str, Any] | None = None
    committed: bool = False
    replayed: bool = False
    type: Literal['allocation'] | None = None
    explanation: str | None = None
    allocation: AllocationRecommendationResult | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
