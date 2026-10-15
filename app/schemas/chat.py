"""Chat v2 inputs and context-aware interpretation, independent of parser_v1."""
from typing import Any, Literal
from pydantic import Field, model_validator
from app.schemas.api import Input, Output, Identifier, Version, Objective

Intent = Literal['new_request', 'allocate_request', 'answer_clarification', 'modify_constraints',
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
    action: Literal['message', 'new_request', 'confirm', 'archive'] = 'message'
    message: str = Field(default='', max_length=10000)
    recommendation_id: Identifier | None = None

    @model_validator(mode='after')
    def confirmation_target(self):
        if self.action=='confirm' and not self.recommendation_id:
            raise ValueError('confirmation requires recommendation_id')
        return self


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
    candidate_intents: list[str] = Field(default_factory=list)
    ambiguity_reason: str | None = None
    referenced_order_id: str | None = None
    referenced_recommendation_id: str | None = None
    patch_operations: list[PatchOperation] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list)
    answered_question_ids: list[str] = Field(default_factory=list)


class ChatOutput(Output):
    session_id: str
    session_version: int
    assistant_message: dict[str, Any] | None = None
    committed: bool = False
    replayed: bool = False
