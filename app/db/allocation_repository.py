"""Allocation writes. Caller owns the business transaction and decision ordering."""
import json
from app.db.database import utc_now


def capacity(connection, workshop_id):
    return connection.execute("SELECT capacity_pieces_per_day FROM workshops WHERE workshop_id=?",
                              (workshop_id,)).fetchone()[0]


def insert_working_order(connection, order_id, part, request_id, objective, capacity_at_assignment):
    connection.execute("""INSERT INTO working_order
        (order_id,workshop_id,request_id,pieces,estimated_days,estimated_cost,objective,assigned_at,
         capacity_at_assignment,queue_remaining_days) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
        order_id, part["workshop_id"], request_id, part["pieces"], part["estimated_days"],
        part["estimated_cost"], objective, utc_now(), capacity_at_assignment, part["processing_days"]))


def set_queue(connection, workshop_id, after, as_of):
    connection.execute("UPDATE workshop_queue SET current_queue_days=?,as_of_date=? WHERE workshop_id=?",
                       (after, as_of.isoformat(), workshop_id))


def mark_working(connection, order_id):
    connection.execute("UPDATE orders SET state='WORKING',version=version+1 WHERE order_id=?", (order_id,))
    connection.execute("DELETE FROM unassigned_order WHERE order_id=?", (order_id,))


def mark_unassigned(connection, order_id, request_id, reason):
    connection.execute("""INSERT INTO unassigned_order VALUES (?,?,?,?)
        ON CONFLICT(order_id) DO UPDATE SET request_id=excluded.request_id,
        reason=excluded.reason,updated_at=excluded.updated_at""",
        (order_id, request_id, reason, utc_now()))
    connection.execute("UPDATE orders SET state='UNASSIGNED',version=version+1 WHERE order_id=?", (order_id,))


def record_decision(connection, request_id, fingerprint, message, outcome, response):
    now = utc_now()
    result = response["result"]
    connection.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,NULL)", (
        request_id, now, fingerprint, message, result["decision_status"],
        json.dumps(response), json.dumps(outcome.telemetry)))
    parsed = outcome.parsed
    if parsed:
        values = [request_id, now, message]
        fields = ("order_id", "customer", "product", "category", "pieces", "order_date", "due_date", "objective",
                  "exclusion", "num_workshop_allowed", "preferred_workshop", "deadline_required", "parse_status",
                  "missing_fields", "ambiguities")
        values.extend(json.dumps(getattr(parsed, f)) if isinstance(getattr(parsed, f), list)
                      else getattr(parsed, f) for f in fields)
        connection.execute("INSERT INTO request_parsing_history VALUES (" + ",".join("?" for _ in values) + ")", values)
    order_id = response.get("trace", {}).get("order", {}).get("order_id")
    connection.execute("""INSERT INTO decision_log (request_id,order_id,decision_status,reason_codes,objective,decision_json,created_at)
                          VALUES (?,?,?,?,?,?,?)""", (request_id, order_id, result["decision_status"],
                          json.dumps(result["reason_codes"]), result.get("objective"), json.dumps(result), now))
