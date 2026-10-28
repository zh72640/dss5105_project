"""Shared decision helpers for lifecycle and offline test seeding.

HTTP ``/api/requests`` (Parser v1) has been retired. Chat v2 owns conversational
allocation. Production events reuse decide/apply via this module.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import date

from app.db.database import Database
from app.schemas.parser_schema import OBJECTIVES, ParseResult
from app.services.allocation.service import apply as _apply, decide as _decide, record as _record
from app.services.intake.rule_parser import extract

PIPELINE_VERSION = "mvp_v0.2"
ALIASES = {"min_lateness": "min_delay", "fastest_turnaround": "min_delay"}


def terminal(status, code, message):
    return {"success": False, "decision_status": status, "allocation": [], "reason_codes": [code],
            "warnings": [], "message": message, "candidate_ranking": []}


def _cached(connection, request_id, fingerprint):
    row = connection.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        return None
    if row["fingerprint"] != fingerprint:
        return {"request_id": request_id, "result": terminal("ERROR", "IDEMPOTENCY_CONFLICT",
                "This request ID belongs to different input or configuration."), "replayed": False}
    response = json.loads(row["response_json"])
    response["replayed"] = True
    return response


def seed_allocation(text: str, objective="min_delay", *, db_path=None, database=None,
                    request_id=None, as_of=date(2026, 4, 1), actor=None):
    """Offline rule extract + decide/apply for tests and demos (not an HTTP API)."""
    if not isinstance(objective, str) or not isinstance(as_of, date):
        return {"request_id": request_id, "result": terminal("ERROR", "INVALID_ARGUMENT", "Check objective/as_of.")}
    objective = ALIASES.get(objective, objective)
    request_id = str(uuid.uuid4()) if request_id is None else request_id
    if objective not in OBJECTIVES or not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        return {"request_id": request_id, "result": terminal("ERROR", "INVALID_ARGUMENT", "Check objective/request_id.")}
    if not isinstance(text, str):
        return {"request_id": request_id, "result": terminal("DECLINE", "INVALID_MESSAGE", "Message must be text.")}
    if actor is not None and (not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 120):
        return {"request_id": request_id, "result": terminal("ERROR", "INVALID_ARGUMENT", "Invalid actor.")}
    config = [text, objective, as_of.isoformat(), "rules_v1", PIPELINE_VERSION]
    if actor is not None:
        config.append(actor)
    fingerprint = hashlib.sha256(json.dumps(config).encode()).hexdigest()
    owned = database is None
    db = database
    response = {"request_id": request_id, "pipeline_version": PIPELINE_VERSION, "as_of_date": as_of.isoformat(),
                "raw_message": text, "replayed": False, "trace": {"db_changes": []}}
    outcome = None
    try:
        db = db or Database(db_path or ":memory:")
        cached = _cached(db.connection, request_id, fingerprint)
        if cached:
            return cached
        parsed = ParseResult(**extract(text, as_of))
        class _Outcome:
            pass
        outcome = _Outcome()
        outcome.parsed = parsed
        outcome.telemetry = {"backend": "offline", "prompt_version": "rules_v1"}
        outcome.error = None
        response["parsed"] = parsed.to_dict()
        response["request"] = response["parsed"]
        response["parser_telemetry"] = outcome.telemetry
        with db.transaction() as connection:
            cached = _cached(connection, request_id, fingerprint)
            if cached:
                return cached
            result = _decide(connection, parsed, objective, as_of, response["trace"])
            result["request_id"] = request_id
            response["result"] = result
            _record(connection, request_id, fingerprint, text, outcome, response)
            if actor is not None:
                connection.execute("INSERT INTO request_actors VALUES (?,?)", (request_id, actor))
            _apply(connection, request_id, result, response["trace"], as_of)
            response["trace"]["db_changes"].extend([{"table": "requests", "inserted_rows": 1},
                {"table": "request_parsing_history", "inserted_rows": 1},
                {"table": "decision_log", "inserted_rows": 1}])
            connection.execute("UPDATE requests SET response_json=? WHERE request_id=?",
                               (json.dumps(response), request_id))
        return response
    except (sqlite3.Error, OSError, ValueError) as error:
        code = str(error) if isinstance(error, ValueError) else "DB_ERROR"
        response["result"] = terminal("ERROR", code, "Request failed; business transaction rolled back.")
        response["trace"]["db_changes"] = []
        response["error_type"] = type(error).__name__
        response["error_logged"] = False
        return response
    finally:
        if owned and db:
            db.close()
