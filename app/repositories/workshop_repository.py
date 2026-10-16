from datetime import date
from app.tools.models import Workshop


def get_all(connection, as_of):
    rows = connection.execute("""SELECT w.*, q.current_queue_days, q.as_of_date FROM workshops w
                               LEFT JOIN workshop_queue q USING(workshop_id) ORDER BY workshop_id""").fetchall()
    result = []
    for r in rows:
        if r["current_queue_days"] is None:
            raise ValueError("QUEUE_DATA_MISSING")
        elapsed = (as_of - date.fromisoformat(r["as_of_date"])).days
        if elapsed < 0:
            raise ValueError("QUEUE_DATE_REWIND")
        result.append(Workshop(r["workshop_id"], r["name"], r["capacity_pieces_per_day"], r["pickup_lead_days"],
                              r["defect_rate"], r["cost_per_piece"], frozenset(r["makes"].split("+")), r["status"],
                              r["max_batch_pieces"], max(0., r["current_queue_days"] - elapsed), r["notes"]))
    return result
