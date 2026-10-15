"""Deterministic queue aging and release rules used by dispatch and lifecycle."""
import math
from datetime import date

from app.db import queue_repository as repository


def advance(connection, workshop_id, as_of):
    """Age a workshop's reservations exactly once inside the caller's transaction."""
    queue = repository.get_queue(connection, workshop_id)
    if queue is None:
        raise ValueError("QUEUE_DATA_MISSING")
    elapsed = (as_of - date.fromisoformat(queue["as_of_date"])).days
    if elapsed < 0:
        raise ValueError("QUEUE_DATE_REWIND")
    rows = repository.working_orders(connection, workshop_id)
    accounted = queue["baseline_queue_days"] + sum(row["queue_remaining_days"] for row in rows)
    if not math.isclose(accounted, queue["current_queue_days"], abs_tol=1e-8):
        raise ValueError("QUEUE_ACCOUNTING_MISMATCH")
    baseline = max(0., queue["baseline_queue_days"] - elapsed)
    elapsed = max(0., elapsed - queue["baseline_queue_days"])
    total = baseline
    for row in rows:
        remaining = max(0., row["queue_remaining_days"] - elapsed)
        elapsed = max(0., elapsed - row["queue_remaining_days"])
        if remaining != row["queue_remaining_days"]:
            repository.set_remaining_at_position(connection, row["position"], remaining)
        total += remaining
    repository.set_aged_queue(connection, workshop_id, total, baseline, as_of)


def release(connection, order_id, workshop_id, completed_pieces=None):
    """Release only this allocation's unelapsed reservation."""
    row = repository.get_working_order(connection, order_id, workshop_id)
    remaining = 0. if completed_pieces is None else min(
        row["queue_remaining_days"], (row["pieces"] - completed_pieces) / row["capacity_at_assignment"])
    released = max(0., row["queue_remaining_days"] - remaining)
    repository.set_working_remaining(connection, order_id, workshop_id, remaining)
    repository.subtract_queue(connection, workshop_id, released)
    return released
