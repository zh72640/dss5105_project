"""Shared allocation request fields used by Chat and Offline rules."""
from dataclasses import asdict, dataclass, field

OBJECTIVES = ("min_delay", "min_cost", "min_defects", "hybrid")


@dataclass(frozen=True)
class ParseResult:
    order_id: str | None = None
    customer: str | None = None
    product: str | None = None
    category: str | None = None
    pieces: int | None = None
    order_date: str | None = None
    due_date: str | None = None
    objective: str | None = None
    exclusion: list[str] = field(default_factory=list)
    num_workshop_allowed: int | None = None
    parse_status: str = "needs_clarification"
    missing_fields: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    # Preserve named-workshop requests and explicit hard deadlines.
    preferred_workshop: str | None = None
    deadline_required: bool = False

    def to_dict(self):
        return asdict(self)
