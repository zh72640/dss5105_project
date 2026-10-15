"""HTTP contracts; strict inputs prevent implicit conversion of versions and IDs."""
from typing import Any, Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Version = Annotated[int, Field(ge=0)]
Objective = Literal["min_delay", "min_cost", "min_defects", "hybrid"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Output(BaseModel):
    # Domain response fields remain available while HTTP contracts grow incrementally.
    model_config = ConfigDict(extra="allow")


class LoginInput(Input):
    username: str
    password: str


class EmptyInput(Input):
    pass


class DispatchInput(Input):
    message: str = Field(min_length=1, max_length=10000)
    objective: str = "min_delay"
    request_id: Identifier | None = None
    mode: Literal["offline", "llm"] | None = None
    model_key: Identifier | None = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("message must contain text")
        return value


class SessionInput(Input):
    session_id: Identifier | None = None
    objective: Objective = "min_delay"
    mode: Literal["offline", "llm"] | None = None
    model_key: Identifier | None = None


class TurnInput(Input):
    request_id: Identifier
    expected_version: Version
    action: Literal["message", "replace", "confirm", "close"] = "message"
    message: str = Field(default="", max_length=10000)
    changes: dict[str, Any] | None = None
    mode: Literal["offline", "llm"] | None = None
    model_key: Identifier | None = None


class EventInput(Input):
    action: Literal["complete", "cancel", "lapse", "reassign"]
    order_id: str
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: Version
    event_id: Identifier
    workshop_id: str | None = None
    pieces: int | None = None
    objective: str = "min_delay"
    exclusion: list[str] | None = None
    max_workshops: int = 1
    preferred_workshop: str | None = None
    deadline_required: bool = False


class JobCreateInput(Input):
    kind: str
    session_id: Identifier
    message: str = Field(min_length=1, max_length=10000)
    request_id: Identifier | None = None
    expected_version: Version | None = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("message must contain text")
        return value


class ErrorOutput(Output):
    error: str
    message: str | None = None


class Decision(Output):
    success: bool
    decision_status: str
    allocation: list[dict[str, Any]] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    message: str


class SessionSnapshot(Output):
    session_id: str
    state: Literal["ACTIVE", "AWAITING_CLARIFICATION", "CLOSED"]
    version: int
    draft: dict[str, Any]
    blockers: list[str]


class SessionOutput(Output):
    session: SessionSnapshot | None = None
    result: Decision | None = None
    replayed: bool = False
    committed: bool = False


class DispatchOutput(Output):
    result: Decision
    replayed: bool = False


class JobOutput(Output):
    job_id: str
    kind: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    session_id: str | None = None
    progress: dict[str, Any]
    result: dict[str, Any] | None = None


class ItemsOutput(Output):
    items: list[dict[str, Any]]


class OrderOutput(Output):
    order_id: str
    state: str
    version: int
    remaining_pieces: int
    allocations: list[dict[str, Any]]


class HealthOutput(Output):
    status: str
    backend: str
    as_of_date: str
    version: str
    pipeline_version: str


class IdentityOutput(Output):
    username: str | None
    role: Literal["user", "admin"] | None
    auth_required: bool
    setup_required: bool


class LoginOutput(Output):
    username: str
    role: Literal["user", "admin"]
