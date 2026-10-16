"""FIFO reservations separate forecast queue decay from confirmed production."""
import math
from datetime import date


def advance(connection, workshop_id, as_of):
    """Age a workshop's reservations exactly once, inside the caller's transaction."""
    queue = connection.execute("SELECT * FROM workshop_queue WHERE workshop_id=?", (workshop_id,)).fetchone()
    if queue is None:
        raise ValueError("QUEUE_DATA_MISSING")
    elapsed = (as_of - date.fromisoformat(queue["as_of_date"])).days
    if elapsed < 0:
        raise ValueError("QUEUE_DATE_REWIND")
    rows = connection.execute("SELECT rowid AS position,* FROM working_order WHERE workshop_id=? ORDER BY rowid",
                              (workshop_id,)).fetchall()
    accounted = queue["baseline_queue_days"] + sum(r["queue_remaining_days"] for r in rows)
    if not math.isclose(accounted, queue["current_queue_days"], abs_tol=1e-8):
        raise ValueError("QUEUE_ACCOUNTING_MISMATCH")
    baseline = max(0., queue["baseline_queue_days"] - elapsed)
    elapsed = max(0., elapsed - queue["baseline_queue_days"])
    total = baseline
    for row in rows:
        remaining = max(0., row["queue_remaining_days"] - elapsed)
        elapsed = max(0., elapsed - row["queue_remaining_days"])
        if remaining != row["queue_remaining_days"]:
            connection.execute("UPDATE working_order SET queue_remaining_days=? WHERE rowid=?", (remaining, row["position"]))
        total += remaining
    connection.execute("""UPDATE workshop_queue SET current_queue_days=?,baseline_queue_days=?,as_of_date=?
        WHERE workshop_id=?""", (total, baseline, as_of.isoformat(), workshop_id))


def release(connection, order_id, workshop_id, completed_pieces=None):
    """Release only this allocation's unelapsed reservation; never another job's."""
    row = connection.execute("SELECT * FROM working_order WHERE order_id=? AND workshop_id=?",
                             (order_id, workshop_id)).fetchone()
    remaining = 0. if completed_pieces is None else min(
        row["queue_remaining_days"], (row["pieces"] - completed_pieces) / row["capacity_at_assignment"])
    released = max(0., row["queue_remaining_days"] - remaining)
    connection.execute("UPDATE working_order SET queue_remaining_days=? WHERE order_id=? AND workshop_id=?",
                       (remaining, order_id, workshop_id))
    connection.execute("UPDATE workshop_queue SET current_queue_days=MAX(0,current_queue_days-?) WHERE workshop_id=?",
                       (released, workshop_id))
    return released
