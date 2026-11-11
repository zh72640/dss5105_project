"""Shared contracts for manual registration and its explicit review decisions."""
from datetime import date
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.api import Identifier, Input, Output, Version

ORDER_FIELDS = ("order_id", "customer", "product", "category", "pieces", "order_date", "due_date")
EDITABLE_FIELDS = ORDER_FIELDS[1:]


class OrderFacts(Input):
    order_id: str = Field(pattern=r"^(ORD-[0-9]{3}|O[0-9]+)$", max_length=128)
    customer: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    category: Literal["TOPS", "ACCESSORIES"]
    pieces: int = Field(ge=1, le=2**31 - 1)
    order_date: str
    due_date: str

    @field_validator("order_id", "customer", "product", "category", mode="before")
    @classmethod
    def trim_text(cls, value, info):
        if isinstance(value, str):
            value = value.strip()
            if info.field_name in {"order_id", "category"}:
                value = value.upper()
        return value

    @field_validator("order_date", "due_date")
    @classmethod
    def iso_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Dates must use YYYY-MM-DD.")
        return value

    @model_validator(mode="after")
    def date_order(self):
        if self.due_date < self.order_date:
            raise ValueError("Due date cannot precede order date.")
        return self


class OrderReviewInput(Input):
    request_id: Identifier
    order: OrderFacts


class OrderDecisionInput(Input):
    request_id: Identifier
    action: Literal["create", "update", "reject"]
    expected_version: Version | None
    reason: str = Field(min_length=1, max_length=2000)
    confirmed_order_id: str = Field(default="", max_length=128)
    verified_fields: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("reason")
    @classmethod
    def reason_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("A reason is required.")
        return value


class OrderDecisionOutput(Output):
    request_id: str
    review_id: str
    action: str
    actor: str
    reason: str
    outcome: str
    applied: bool
    message: str
    order: dict[str, Any] | None
    created_at: str
    replayed: bool = False


class OrderReviewOutput(Output):
    review_id: str
    request_id: str
    actor: str
    order_id: str
    submitted: dict[str, Any]
    proposed: OrderFacts
    existing: dict[str, Any] | None
    differences: list[dict[str, Any]]
    match: Literal["missing", "identical", "different"]
    expected_version: int | None
    can_update: bool
    update_blocker: str | None
    created_at: str
    decision: dict[str, Any] | None = None
    replayed: bool = False


class OrderHistoryOutput(Output):
    items: list[OrderReviewOutput]
    total: int
    limit: int
    offset: int
