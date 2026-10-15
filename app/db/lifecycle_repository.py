"""Production allocation and audit persistence. The lifecycle service owns decisions."""
import json
from app.db.database import utc_now


def snapshot(connection, order_id):
    row = connection.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        return None
    allocations = [dict(r) for r in connection.execute(
        "SELECT * FROM working_order WHERE order_id=? ORDER BY workshop_id", (order_id,))]
    return {**dict(row), "remaining_pieces": row["pieces"] - row["completed_pieces"],
            "allocations": allocations}


def recent_events(connection, order_id):
    return [dict(r) for r in connection.execute("""SELECT event_id,action,actor,reason,
        as_of_date,expected_version,applied,created_at FROM lifecycle_events
        WHERE order_id=? ORDER BY rowid DESC LIMIT 30""", (order_id,))]


def last_applied_date(connection, order_id):
    return connection.execute("SELECT MAX(as_of_date) FROM lifecycle_events WHERE order_id=? AND applied=1",
                              (order_id,)).fetchone()[0]


def allocation_part(connection, order_id, workshop_id):
    return connection.execute("SELECT * FROM working_order WHERE order_id=? AND workshop_id=?",
                              (order_id, workshop_id)).fetchone()


def finish_part(connection, order_id, part, completed, total, state):
    connection.execute("UPDATE working_order SET completed_pieces=? WHERE order_id=? AND workshop_id=?",
                       (completed, order_id, part["workshop_id"]))
    if completed == part["pieces"]:
        connection.execute("DELETE FROM working_order WHERE order_id=? AND workshop_id=?",
                           (order_id, part["workshop_id"]))
    connection.execute("UPDATE orders SET completed_pieces=?,state=?,version=version+1 WHERE order_id=?",
                       (total, state, order_id))
    if state == "COMPLETED":
        connection.execute("INSERT INTO completed_order VALUES (?,?)", (order_id, utc_now()))


def clear_assignments(connection, order_id):
    connection.execute("DELETE FROM working_order WHERE order_id=?", (order_id,))
    connection.execute("DELETE FROM unassigned_order WHERE order_id=?", (order_id,))


def set_ready(connection, order_id):
    connection.execute("UPDATE orders SET state='READY' WHERE order_id=?", (order_id,))


def set_terminal(connection, order_id, state, reason=None):
    connection.execute("UPDATE orders SET state=?,version=version+1 WHERE order_id=?", (state, order_id))
    if state == "LAPSED":
        connection.execute("INSERT INTO lapsed_order VALUES (?,?,?)", (order_id, reason, utc_now()))


def create_request(connection, event_id, now, fingerprint, message):
    connection.execute("""INSERT INTO requests
        (request_id,request_date_time,fingerprint,original_message,status,response_json,telemetry_json)
        VALUES (?,?,?,?,?,?,?)""", (event_id, now, fingerprint, message, "PENDING", "{}", '{"kind":"lifecycle"}'))


def record_audit(connection, event_id, order_id, action, payload, as_of, expected_version,
                 result, before, after, now, response):
    if before:
        connection.execute("INSERT INTO lifecycle_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            event_id, order_id, action, payload["actor"], payload["reason"], as_of.isoformat(), expected_version,
            int(result["success"]), json.dumps(before), json.dumps(after), now))
    connection.execute("""INSERT INTO decision_log
        (request_id,order_id,decision_status,reason_codes,objective,decision_json,created_at) VALUES (?,?,?,?,?,?,?)""",
        (event_id, order_id if before else None, result["decision_status"], json.dumps(result["reason_codes"]),
         result.get("objective"), json.dumps(result), now))
    connection.execute("UPDATE requests SET status=?,response_json=? WHERE request_id=?",
                       (result["decision_status"], json.dumps(response), event_id))


def begin_read(connection):
    connection.execute("BEGIN")


def commit_read(connection):
    connection.execute("COMMIT")


def rollback_read(connection):
    connection.execute("ROLLBACK")


def begin_change(connection):
    connection.execute("SAVEPOINT lifecycle_change")


def rollback_change(connection):
    connection.execute("ROLLBACK TO lifecycle_change")


def release_change(connection):
    connection.execute("RELEASE lifecycle_change")
