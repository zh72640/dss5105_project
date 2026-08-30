from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Constraint:
    type: str
    value: Any
    source_text: str | None = None


@dataclass(frozen=True)
class StructuredRequest:
    request_id: str | None = None
    order_id: str | None = None
    customer: str | None = None
    product: str | None = None
    category: str | None = None
    quantity: int | None = None
    required_date: str | None = None
    preferred_workshop: str | None = None
    excluded_workshops: list[str] = field(default_factory=list)
    objective_override: str | None = None
    constraints: list[Constraint] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

