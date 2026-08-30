from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    order_id: str
    customer: str
    product: str
    category: str
    pieces: int
    due_date: str


@dataclass(frozen=True)
class Workshop:
    workshop_id: str
    name: str
    capacity: int
    lead_days: int
    defect_rate: float
    cost: float
    makes: frozenset[str]
    status: str
    max_batch: int | None
    queue_days: float
    notes: str

