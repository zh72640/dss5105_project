"""Frozen parser_v1 contract; transport/telemetry live outside this model."""
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "parser_v1"
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
    # v1 retains Week 4's named-workshop requests and explicit hard deadlines.
    preferred_workshop: str | None = None
    deadline_required: bool = False

    def to_dict(self):
        return asdict(self)


def json_schema():
    props = {key: {"type": ["string", "null"]} for key in
             ("order_id", "customer", "product", "category", "order_date", "due_date", "preferred_workshop")}
    props.update({key: {"type": ["integer", "null"]} for key in ("pieces", "num_workshop_allowed")})
    props["objective"] = {"type": ["string", "null"], "enum": [*OBJECTIVES, None]}
    props["category"] = {"type": ["string", "null"], "enum": ["TOPS", "ACCESSORIES", None]}
    for key in ("exclusion", "missing_fields", "ambiguities"):
        props[key] = {"type": "array", "items": {"type": "string"}}
    props["parse_status"] = {"type": "string", "enum": ["ok", "needs_clarification", "invalid"]}
    props["deadline_required"] = {"type": "boolean"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
