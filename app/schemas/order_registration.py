"""Evidence-bearing chat entry; confirmation remains an explicit HTTP action."""
from typing import Any, Literal
from pydantic import Field
from app.schemas.api import Input, Identifier, Version
from app.schemas.order_intake import OrderDecisionInput


class RegistrationPatch(Input):
    field: Literal['order_id', 'customer', 'product', 'category', 'pieces', 'order_date', 'due_date']
    value: Any
    quote: str = Field(min_length=1, max_length=10000)


class RegistrationExtraction(Input):
    intent: Literal['details', 'cancel'] = 'details'
    patches: list[RegistrationPatch] = Field(default_factory=list, max_length=7)
    ambiguity: str | None = Field(default=None, max_length=1000)


class RegistrationDecision(Input):
    review_id: Identifier
    action: Literal['create', 'update', 'reject']
    expected_version: Version | None
    reason: str = Field(min_length=1, max_length=2000)
    confirmed_order_id: str = Field(default='', max_length=128)
    verified_fields: list[str] = Field(default_factory=list, max_length=6)

    def intake_input(self, request_id):
        return OrderDecisionInput.model_validate({
            **self.model_dump(exclude={'review_id'}), 'request_id': request_id}).model_dump()
