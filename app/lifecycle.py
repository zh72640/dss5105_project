"""Explicit, audited production events with optimistic concurrency and atomic reassign."""
import hashlib
import json
import sqlite3
from datetime import date

from app.db.database import Database, utc_now
from app.pipeline import PIPELINE_VERSION, _apply, _cached, _decide, terminal
from app.repositories.queue_repository import advance, release
from app.schemas.parser_schema import OBJECTIVES, ParseResult

ACTIONS = ("complete", "cancel", "lapse", "reassign")


def snapshot(connection, order_id):
    row = connection.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        return None
    allocations = [dict(r) for r in connection.execute(
        "SELECT * FROM working_order WHERE order_id=? ORDER BY workshop_id", (order_id,))]
    return {**dict(row), "remaining_pieces": row["pieces"] - row["completed_pieces"], "allocations": allocations}


def inspect_order(order_id, *, db_path=None, database=None):
    owned = database is None
    db = database or Database(db_path or ":memory:")
    try:
        # Read the state and audit together, without observing an intervening event.
        db.connection.execute("BEGIN")
        try:
            result = snapshot(db.connection, order_id)
            if result:
                result["events"] = [dict(r) for r in db.connection.execute("""SELECT event_id,action,actor,reason,
                    as_of_date,expected_version,applied,created_at FROM lifecycle_events
                    WHERE order_id=? ORDER BY rowid DESC LIMIT 30""", (order_id,))]
            db.connection.execute("COMMIT")
            return result
        except BaseException:
            db.connection.execute("ROLLBACK")
            raise
    finally:
        if owned:
            db.close()


def _valid_text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _check_arguments(action, order_id, actor, reason, expected_version, event_id, as_of,
                     workshop_id, pieces, objective, exclusion, max_workshops, preferred_workshop, deadline_required):
    if not all((_valid_text(order_id, 128), _valid_text(actor, 120), _valid_text(reason, 2000),
                _valid_text(event_id, 128), type(expected_version) is int and expected_version >= 0,
                type(as_of) is date, isinstance(action, str) and action in ACTIONS)):
        return False
    if action == "complete":
        if not _valid_text(workshop_id, 128) or type(pieces) is not int or pieces <= 0:
            return False
    elif workshop_id is not None or pieces is not None:
        return False
    if action != "reassign":
        return (objective == "min_delay" and exclusion is None and max_workshops == 1 and
                preferred_workshop is None and deadline_required is False)
    return (isinstance(objective, str) and objective in OBJECTIVES and
            (exclusion is None or isinstance(exclusion, list) and len(exclusion) <= 100 and
             all(_valid_text(item, 128) for item in exclusion)) and
            type(max_workshops) is int and 1 <= max_workshops <= 8 and
            (preferred_workshop is None or _valid_text(preferred_workshop, 128)) and
            type(deadline_required) is bool)


def _transition(connection, payload, before, response):
    action, order_id = payload["action"], payload["order_id"]
    if before["version"] != payload["expected_version"]:
        return terminal("REFUSE", "VERSION_CONFLICT", "Refresh the order before submitting a new event.")
    allowed = ("READY", "UNASSIGNED", "WORKING") if action == "lapse" else ("WORKING",)
    if before["state"] not in allowed:
        return terminal("REFUSE", "INVALID_ORDER_STATE", "This action is not allowed in the current order state.")
    pending = sum(row["pieces"] - row["completed_pieces"] for row in before["allocations"])
    if (before["state"] == "WORKING" and pending != before["remaining_pieces"] or
            before["state"] != "WORKING" and before["allocations"]):
        raise ValueError("PIECES_CONSERVATION_FAILED")
    if action == "complete":
        part = next((r for r in before["allocations"] if r["workshop_id"] == payload["workshop_id"]), None)
        if not part:
            return terminal("REFUSE", "ALLOCATION_NOT_FOUND", "Select an active allocation for this order.")
        if payload["pieces"] > part["pieces"] - part["completed_pieces"]:
            return terminal("REFUSE", "COMPLETION_EXCEEDS_REMAINING", "Completed pieces exceed the outstanding allocation.")
    as_of = date.fromisoformat(payload["as_of_date"])
    # Even an unassigned order cannot receive backdated lifecycle events.
    last = connection.execute("SELECT MAX(as_of_date) FROM lifecycle_events WHERE order_id=? AND applied=1",
                              (order_id,)).fetchone()[0]
    if last and payload["as_of_date"] < last:
        raise ValueError("EVENT_DATE_REWIND")
    for part in before["allocations"]:
        advance(connection, part["workshop_id"], as_of)
    changes = response["trace"]["db_changes"]
    if action == "complete":
        # 'part' above is deliberately reselected after queue aging.
        part = connection.execute("SELECT * FROM working_order WHERE order_id=? AND workshop_id=?",
                                  (order_id, payload["workshop_id"])).fetchone()
        part_completed = part["completed_pieces"] + payload["pieces"]
        released = release(connection, order_id, part["workshop_id"], part_completed)
        connection.execute("UPDATE working_order SET completed_pieces=? WHERE order_id=? AND workshop_id=?",
                           (part_completed, order_id, part["workshop_id"]))
        if part_completed == part["pieces"]:
            connection.execute("DELETE FROM working_order WHERE order_id=? AND workshop_id=?", (order_id, part["workshop_id"]))
        total = before["completed_pieces"] + payload["pieces"]
        state = "COMPLETED" if total == before["pieces"] else "WORKING"
        connection.execute("UPDATE orders SET completed_pieces=?,state=?,version=version+1 WHERE order_id=?", (total, state, order_id))
        if state == "COMPLETED":
            connection.execute("INSERT INTO completed_order VALUES (?,?)", (order_id, utc_now()))
        changes.append({"table": "working_order", "workshop_id": part["workshop_id"],
                        "completed_pieces_delta": payload["pieces"], "released_queue_days": released})
    else:
        for part in before["allocations"]:
            released = release(connection, order_id, part["workshop_id"])
            changes.append({"table": "workshop_queue", "workshop_id": part["workshop_id"], "released_queue_days": released})
        connection.execute("DELETE FROM working_order WHERE order_id=?", (order_id,))
        connection.execute("DELETE FROM unassigned_order WHERE order_id=?", (order_id,))
        if action == "reassign":
            # A failed plan rolls this savepoint back, including all queue releases.
            connection.execute("UPDATE orders SET state='READY' WHERE order_id=?", (order_id,))
            parsed = ParseResult(order_id=order_id, objective=payload["objective"], exclusion=payload["exclusion"],
                                 num_workshop_allowed=payload["max_workshops"], preferred_workshop=payload["preferred_workshop"],
                                 deadline_required=payload["deadline_required"], parse_status="ok")
            result = _decide(connection, parsed, payload["objective"], as_of, response["trace"])
            if not result["success"]:
                return result
            _apply(connection, payload["event_id"], result, response["trace"], as_of)
            return {**result, "decision_status": "REASSIGNED", "message": "Remaining production reassigned atomically."}
        state = "LAPSED" if action == "lapse" else "READY"
        connection.execute("UPDATE orders SET state=?,version=version+1 WHERE order_id=?", (state, order_id))
        if action == "lapse":
            connection.execute("INSERT INTO lapsed_order VALUES (?,?,?)", (order_id, payload["reason"], utc_now()))
    return {"success": True, "decision_status": action.upper(), "reason_codes": ["LIFECYCLE_APPLIED"],
            "allocation": [], "warnings": [], "message": "Production event recorded.", "candidate_ranking": []}


def process_event(action, order_id, *, actor, reason, expected_version, event_id, db_path=None, database=None,
                  as_of=date(2026, 4, 1), workshop_id=None, pieces=None, objective="min_delay", exclusion=None,
                  max_workshops=1, preferred_workshop=None, deadline_required=False):
    response = {"request_id": event_id, "replayed": False, "pipeline_version": PIPELINE_VERSION, "trace": {"db_changes": []}}
    if not _check_arguments(action, order_id, actor, reason, expected_version, event_id, as_of,
                            workshop_id, pieces, objective, exclusion, max_workshops, preferred_workshop, deadline_required):
        response["result"] = terminal("ERROR", "INVALID_ARGUMENT", "Check event fields, actor, reason and expected version.")
        return response
    payload = {"action": action, "order_id": order_id, "actor": actor.strip(), "reason": reason.strip(),
               "expected_version": expected_version, "event_id": event_id, "as_of_date": as_of.isoformat(),
               "workshop_id": workshop_id, "pieces": pieces, "objective": objective, "exclusion": sorted(set(exclusion or [])),
               "max_workshops": max_workshops, "preferred_workshop": preferred_workshop, "deadline_required": deadline_required}
    message = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(("lifecycle_v1:" + message).encode()).hexdigest()
    owned, db = database is None, database
    try:
        db = db or Database(db_path or ":memory:")
        with db.transaction() as connection:
            cached = _cached(connection, event_id, fingerprint)
            if cached:
                return cached
            now = utc_now()
            before = snapshot(connection, order_id)
            connection.execute("""INSERT INTO requests
                (request_id,request_date_time,fingerprint,original_message,status,response_json,telemetry_json)
                VALUES (?,?,?,?,?,?,?)""", (event_id, now, fingerprint, message, "PENDING", "{}", '{"kind":"lifecycle"}'))
            connection.execute("SAVEPOINT lifecycle_change")
            try:
                result = (_transition(connection, payload, before, response) if before else
                          terminal("REFUSE", "ORDER_NOT_FOUND", "Order does not exist."))
                if not result["success"]:
                    connection.execute("ROLLBACK TO lifecycle_change")
                    response["trace"] = {"db_changes": []}
            except (sqlite3.Error, ValueError) as error:
                connection.execute("ROLLBACK TO lifecycle_change")
                code = str(error) if isinstance(error, ValueError) else "DB_ERROR"
                result = terminal("ERROR", code, "Event failed; business changes rolled back.")
                response["trace"] = {"db_changes": []}
            finally:
                connection.execute("RELEASE lifecycle_change")
            after = snapshot(connection, order_id)
            response.update(result=result, order=after, event=payload)
            result["request_id"] = event_id
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
        return response
    except (sqlite3.Error, OSError, ValueError):
        # A failed audit write also rolls back the business event.
        response.update(result=terminal("ERROR", "DB_ERROR", "Event transaction could not be recorded."),
                        trace={"db_changes": []}, error_logged=False)
        response.pop("order", None)
        return response
    finally:
        if owned and db:
            db.close()
