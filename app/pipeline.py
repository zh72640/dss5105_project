"""MVP v0.1: immutable parse -> deterministic decision -> atomic persistence."""
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import date
from app.agent.parser import parse_with_telemetry
from app.agent.llm_client import GEMINI_MODEL, GEMINI_PROVIDER
from app.allocator.planner import plan
from app.db.database import Database, utc_now
from app.repositories.order_repository import retrieve
from app.repositories.workshop_repository import get_all
from app.schemas.parser_schema import OBJECTIVES

PIPELINE_VERSION = "mvp_v0.1"
ALIASES = {"min_lateness": "min_delay", "fastest_turnaround": "min_delay"}


def terminal(status, code, message):
    return {"success": False, "decision_status": status, "allocation": [], "reason_codes": [code],
            "warnings": [], "message": message, "candidate_ranking": []}


def _cached(connection, request_id, fingerprint):
    row = connection.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        return None
    if row["fingerprint"] != fingerprint:
        return {"request_id": request_id, "result": terminal("ERROR", "IDEMPOTENCY_CONFLICT", "This request ID belongs to different input or configuration."), "replayed": False}
    response = json.loads(row["response_json"])
    response["replayed"] = True
    return response


def _record(connection, request_id, fingerprint, message, outcome, response):
    now = utc_now()
    result = response["result"]
    connection.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,NULL)", (
        request_id, now, fingerprint, message, result["decision_status"], json.dumps(response), json.dumps(outcome.telemetry)))
    parsed = outcome.parsed
    if parsed:
        values = [request_id, now, message]
        fields = ("order_id", "customer", "product", "category", "pieces", "order_date", "due_date", "objective",
                  "exclusion", "num_workshop_allowed", "preferred_workshop", "deadline_required", "parse_status",
                  "missing_fields", "ambiguities")
        values.extend(json.dumps(getattr(parsed, f)) if isinstance(getattr(parsed, f), list) else getattr(parsed, f) for f in fields)
        connection.execute("INSERT INTO request_parsing_history VALUES (" + ",".join("?" for _ in values) + ")", values)
    order_id = response.get("trace", {}).get("order", {}).get("order_id")
    connection.execute("""INSERT INTO decision_log (request_id,order_id,decision_status,reason_codes,objective,decision_json,created_at)
                          VALUES (?,?,?,?,?,?,?)""", (request_id, order_id, result["decision_status"],
                          json.dumps(result["reason_codes"]), result.get("objective"), json.dumps(result), now))


def _decide(connection, parsed, objective, as_of, trace):
    if parsed.parse_status != "ok":
        if parsed.parse_status == "invalid":
            return terminal("DECLINE", "INVALID_REQUEST", "Unsupported or invalid request: " + ", ".join(parsed.ambiguities))
        return terminal("CLARIFY", "PARSER_NEEDS_CLARIFICATION", "Please provide a complete new message: " +
                        ", ".join(parsed.missing_fields + parsed.ambiguities))
    order, issue = retrieve(connection, parsed)
    if order:
        trace["order"] = order
    if issue:
        status = "DECLINE" if issue == "ORDER_NOT_FOUND" else "CLARIFY"
        return terminal(status, issue, "Order lookup could not establish a matching record; no allocation was attempted.")
    if order["state"] in ("WORKING", "COMPLETED", "LAPSED"):
        return terminal("REFUSE", "ORDER_ALREADY_" + order["state"], "Order state prevents another allocation.")
    workshops = get_all(connection, as_of)
    trace["workshop_count"] = len(workshops)
    trace["queue"] = {w.workshop_id: w.queue_days for w in workshops}
    unknown = set(parsed.exclusion) - {w.workshop_id for w in workshops}
    if unknown:
        return terminal("CLARIFY", "UNKNOWN_EXCLUDED_WORKSHOP", "Unknown workshop ID(s): " + ", ".join(sorted(unknown)))
    result = plan(order, workshops, parsed, parsed.objective or objective, as_of)
    trace["eligible_workshops"] = result["eligible_workshops"]
    trace["rejected_workshops"] = result["rejected"]
    return result


def _apply(connection, request_id, result, trace, as_of):
    changes = trace["db_changes"]
    order = trace.get("order")
    if not order or order["state"] not in ("READY", "UNASSIGNED"):
        return
    if result["success"]:
        if sum(p["pieces"] for p in result["allocation"]) != order["pieces"]:
            raise ValueError("PIECES_CONSERVATION_FAILED")
        for part in result["allocation"]:
            connection.execute("INSERT INTO working_order VALUES (?,?,?,?,?,?,?,?)", (
                order["order_id"], part["workshop_id"], request_id, part["pieces"], part["estimated_days"],
                part["estimated_cost"], result["objective"], utc_now()))
            # Processing consumes queue; transport is not workshop production capacity.
            after = part["queue_days"] + part["processing_days"]
            connection.execute("UPDATE workshop_queue SET current_queue_days=?,as_of_date=? WHERE workshop_id=?",
                               (after, as_of.isoformat(), part["workshop_id"]))
            changes.append({"table": "workshop_queue", "workshop_id": part["workshop_id"],
                            "before": part["queue_days"], "after": after})
        connection.execute("UPDATE orders SET state='WORKING' WHERE order_id=?", (order["order_id"],))
        connection.execute("DELETE FROM unassigned_order WHERE order_id=?", (order["order_id"],))
        changes.append({"table": "working_order", "inserted_rows": len(result["allocation"]), "order_id": order["order_id"]})
    elif result["decision_status"] == "ESCALATE" or (result["decision_status"] == "REFUSE" and "rejected" in result):
        connection.execute("INSERT INTO unassigned_order VALUES (?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET request_id=excluded.request_id,reason=excluded.reason,updated_at=excluded.updated_at",
                           (order["order_id"], request_id, result["reason_codes"][0], utc_now()))
        connection.execute("UPDATE orders SET state='UNASSIGNED' WHERE order_id=?", (order["order_id"],))
        changes.append({"table": "unassigned_order", "order_id": order["order_id"], "reason": result["reason_codes"][0]})


def process_request(text: str, objective="min_delay", *, db_path=None, database=None,
                    request_id=None, backend=None, as_of=date(2026, 4, 1)):
    if not isinstance(objective, str) or not isinstance(as_of, date):
        return {"request_id": request_id, "result": terminal("ERROR", "INVALID_ARGUMENT", "Check objective/as_of.")}
    objective = ALIASES.get(objective, objective)
    request_id = str(uuid.uuid4()) if request_id is None else request_id
    if objective not in OBJECTIVES or not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        return {"request_id": request_id, "result": terminal("ERROR", "INVALID_ARGUMENT", "Check objective/request_id.")}
    if not isinstance(text, str):
        return {"request_id": request_id, "result": terminal("DECLINE", "INVALID_MESSAGE", "Message must be text.")}
    backend_name = backend if isinstance(backend, str) else getattr(backend, "name", None) or os.getenv("PARSER_BACKEND", "offline")
    config = [text, objective, as_of.isoformat(), backend_name,
              [GEMINI_PROVIDER, GEMINI_MODEL, 0.0] if backend_name == "llm" else "rules_v1", PIPELINE_VERSION]
    fingerprint = hashlib.sha256(json.dumps(config).encode()).hexdigest()
    owned = database is None
    db = database
    outcome = None
    response = {"request_id": request_id, "pipeline_version": PIPELINE_VERSION, "as_of_date": as_of.isoformat(),
                "raw_message": text, "replayed": False, "trace": {"db_changes": []}}
    try:
        db = db or Database(db_path or ":memory:")
        cached = _cached(db.connection, request_id, fingerprint)
        if cached:
            return cached
        outcome = parse_with_telemetry(text, context_messages=[], backend=backend, reference_date=as_of)
        response["parsed"] = outcome.parsed.to_dict() if outcome.parsed else None
        response["request"] = response["parsed"]  # compatibility envelope; schema is explicitly v1
        response["parser_telemetry"] = outcome.telemetry
        with db.transaction() as connection:
            # Recheck under write lock: two simultaneous callers can parse, only one commits.
            cached = _cached(connection, request_id, fingerprint)
            if cached:
                return cached
            result = terminal("ERROR", "PARSER_ERROR", outcome.error) if outcome.error else _decide(connection, outcome.parsed, objective, as_of, response["trace"])
            result["request_id"] = request_id
            response["result"] = result
            _record(connection, request_id, fingerprint, text, outcome, response)
            _apply(connection, request_id, result, response["trace"], as_of)
            response["trace"]["db_changes"].extend([{"table": "requests", "inserted_rows": 1},
                {"table": "request_parsing_history", "inserted_rows": int(outcome.parsed is not None)},
                {"table": "decision_log", "inserted_rows": 1}])
            connection.execute("UPDATE requests SET response_json=? WHERE request_id=?", (json.dumps(response), request_id))
        return response
    except (sqlite3.Error, OSError, ValueError) as error:
        # DB exceptions roll back all business writes; audit is a separate best-effort transaction.
        code = str(error) if isinstance(error, ValueError) else "DB_ERROR"
        response["result"] = terminal("ERROR", code, "Request failed; business transaction rolled back.")
        response["trace"]["db_changes"] = []
        response["error_type"] = type(error).__name__
        response["error_logged"] = False
        if db and outcome:
            try:
                with db.transaction() as connection:
                    if not _cached(connection, request_id, fingerprint):
                        response["error_logged"] = True
                        _record(connection, request_id, fingerprint, text, outcome, response)
            except sqlite3.Error:
                response["error_logged"] = False
        return response
    finally:
        if owned and db:
            db.close()
