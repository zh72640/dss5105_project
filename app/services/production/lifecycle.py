"""Explicit, audited production events with optimistic concurrency and atomic reassign."""
import hashlib
import json
import sqlite3
from datetime import date

from app.db.database import Database, utc_now
from app.db import lifecycle_repository as repo
from app.db import tracking_repository
from app.services.production import tracking
from app.services.allocation.service import apply as _apply, decide as _decide
from app.services.allocation.dispatch import PIPELINE_VERSION, _cached, terminal
from app.services.production.queue import advance, release
from app.schemas.parser_schema import OBJECTIVES, ParseResult

ACTIONS = ("complete", "cancel", "lapse", "reassign")


def _valid_text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _check_arguments(action, order_id, actor, reason, expected_version, event_id, as_of,
                     workshop_id, pieces, objective, exclusion, max_workshops, preferred_workshop,
                     deadline_required):
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


def _allowed_states(action):
    return ("READY", "UNASSIGNED", "WORKING") if action == "lapse" else ("WORKING",)


def snapshot(connection, order_id):
    return repo.snapshot(connection, order_id)


def inspect_order(order_id, *, db_path=None, database=None):
    owned = database is None
    db = database or Database(db_path or ":memory:")
    try:
        # Read the state and audit together, without observing an intervening event.
        repo.begin_read(db.connection)
        try:
            result = snapshot(db.connection, order_id)
            if result:
                result["events"] = repo.recent_events(db.connection, order_id)
                result["tracking"] = tracking.build(result, tracking_repository.records(db.connection, order_id),
                                                     tracking_repository.completed_at(db.connection, order_id))
            repo.commit_read(db.connection)
            return result
        except BaseException:
            repo.rollback_read(db.connection)
            raise
    finally:
        if owned:
            db.close()


def _transition(connection, payload, before, response):
    action, order_id = payload["action"], payload["order_id"]
    if before["version"] != payload["expected_version"]:
        return terminal("REFUSE", "VERSION_CONFLICT", "Refresh the order before submitting a new event.")
    allowed = _allowed_states(action)
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
    last = repo.last_applied_date(connection, order_id)
    if last and payload["as_of_date"] < last:
        raise ValueError("EVENT_DATE_REWIND")
    for part in before["allocations"]:
        advance(connection, part["workshop_id"], as_of)
    changes = response["trace"]["db_changes"]
    if action == "complete":
        # 'part' above is deliberately reselected after queue aging.
        part = repo.allocation_part(connection, order_id, payload["workshop_id"])
        part_completed = part["completed_pieces"] + payload["pieces"]
        released = release(connection, order_id, part["workshop_id"], part_completed)
        total = before["completed_pieces"] + payload["pieces"]
        state = "COMPLETED" if total == before["pieces"] else "WORKING"
        repo.finish_part(connection, order_id, part, part_completed, total, state)
        changes.append({"table": "working_order", "workshop_id": part["workshop_id"],
                        "completed_pieces_delta": payload["pieces"], "released_queue_days": released})
    else:
        for part in before["allocations"]:
            released = release(connection, order_id, part["workshop_id"])
            changes.append({"table": "workshop_queue", "workshop_id": part["workshop_id"], "released_queue_days": released})
        repo.clear_assignments(connection, order_id)
        if action == "reassign":
            # A failed plan rolls this savepoint back, including all queue releases.
            repo.set_ready(connection, order_id)
            parsed = ParseResult(order_id=order_id, objective=payload["objective"], exclusion=payload["exclusion"],
                                 num_workshop_allowed=payload["max_workshops"], preferred_workshop=payload["preferred_workshop"],
                                 deadline_required=payload["deadline_required"], parse_status="ok")
            result = _decide(connection, parsed, payload["objective"], as_of, response["trace"],
                             max_workshops=payload["max_workshops"])
            if not result["success"]:
                return result
            _apply(connection, payload["event_id"], result, response["trace"], as_of)
            return {**result, "decision_status": "REASSIGNED", "message": "Remaining production reassigned atomically."}
        state = "LAPSED" if action == "lapse" else "READY"
        repo.set_terminal(connection, order_id, state, payload["reason"])
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
            repo.create_request(connection, event_id, now, fingerprint, message)
            repo.begin_change(connection)
            try:
                result = (_transition(connection, payload, before, response) if before else
                          terminal("REFUSE", "ORDER_NOT_FOUND", "Order does not exist."))
                if not result["success"]:
                    repo.rollback_change(connection)
                    response["trace"] = {"db_changes": []}
            except (sqlite3.Error, ValueError) as error:
                repo.rollback_change(connection)
                code = str(error) if isinstance(error, ValueError) else "DB_ERROR"
                result = terminal("ERROR", code, "Event failed; business changes rolled back.")
                response["trace"] = {"db_changes": []}
            finally:
                repo.release_change(connection)
            after = snapshot(connection, order_id)
            response.update(result=result, order=after, event=payload)
            result["request_id"] = event_id
            repo.record_audit(connection, event_id, order_id, action, payload, as_of,
                              expected_version, result, before, after, now, response)
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
