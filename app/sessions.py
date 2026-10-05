"""Versioned clarification drafts with explicit confirmation and atomic allocation.

Parser v1 remains stateless. Follow-ups use a deliberately small, full-match
command grammar; ambiguous/free-form revisions require a complete replacement.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import date

from app.agent.parser import ParserOutcome, parse_with_telemetry
from app.db.database import Database, utc_now
from app.pipeline import _apply, _cached, _decide, _record, terminal
from app.schemas.parser_schema import OBJECTIVES, ParseResult

SESSION_VERSION = "session_v1"
REPLY_HELP = ("Provide an order ID, or use: use two workshops, exclude W3, clear exclusions, "
              "cheapest, fastest, lowest defects. For complex changes use Replace full request. "
              "Review the recommendation before accepting.")


def _identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value))


def _error(code, message=None):
    return {"result": terminal("ERROR", code, message or code), "replayed": False}


def _snapshot(connection, session_id, history=False):
    row = connection.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["draft"] = json.loads(result.pop("draft_json"))
    result["blockers"] = json.loads(result.pop("blockers_json"))
    if history:
        result["messages"] = [dict(r) for r in connection.execute(
            "SELECT sequence,request_id,role,action,content,created_at FROM session_messages WHERE session_id=? ORDER BY sequence",
            (session_id,))]
        latest = connection.execute("""SELECT r.response_json FROM session_messages m
            JOIN requests r USING(request_id) WHERE m.session_id=? AND m.role='assistant'
            ORDER BY m.sequence DESC LIMIT 1""", (session_id,)).fetchone()
        result["last_response"] = json.loads(latest[0]) if latest else None
    return result


def inspect_session(session_id, *, db_path=None, database=None):
    if not _identifier(session_id):
        return None
    if database:
        return _snapshot(database.connection, session_id, True)
    with Database(db_path or ":memory:") as db:
        return _snapshot(db.connection, session_id, True)


def create_session(*, session_id=None, objective="min_delay", backend="offline",
                   as_of=date(2026, 4, 1), db_path=None, database=None):
    session_id = session_id if session_id is not None else str(uuid.uuid4())
    if (not _identifier(session_id) or not isinstance(objective, str) or objective not in OBJECTIVES
            or not isinstance(backend, str) or backend not in ("offline", "llm") or type(as_of) is not date):
        return _error("INVALID_ARGUMENT")
    db = database
    try:
        db = db or Database(db_path or ":memory:")
        with db.transaction() as connection:
            old = _snapshot(connection, session_id)
            if old:
                if (old["objective"], old["backend"], old["as_of_date"]) != (objective, backend, as_of.isoformat()):
                    return _error("IDEMPOTENCY_CONFLICT")
                return {"session": old, "replayed": True}
            now = utc_now()
            connection.execute("INSERT INTO sessions VALUES (?,?,0,?,?,?,?,?,NULL,?,?)", (
                session_id, "AWAITING_CLARIFICATION", objective, backend, as_of.isoformat(),
                json.dumps(ParseResult(missing_fields=["order_id"]).to_dict()), '["order_id"]', now, now))
            return {"session": _snapshot(connection, session_id), "replayed": False}
    except (sqlite3.Error, OSError):
        return _error("DB_ERROR")
    finally:
        if database is None and db:
            db.close()


def _patch(message, draft):
    text = message.strip().rstrip(".!。！").strip()
    out = dict(draft)
    # Every supported edit consumes the whole message, so trailing constraints
    # cannot silently disappear. Never infer which order an unlabelled ID means.
    match = re.fullmatch(r"(?:订单(?:号)?[：: ]*|(?:order(?: id)?[ :]+))?(ORD-\d+)", text, re.I)
    if match:
        out["order_id"] = match[1].upper()
    else:
        if text.lower() in ("reject recommendation", "拒绝推荐"):
            return None, "RECOMMENDATION_REJECTED"
        match = re.fullmatch(r"(?:(?:改成|最多|不超过)\s*([1-8一二两三四五六七八])\s*(?:个|家)?工坊|(?:use|at most|change to) (one|two|three|four|five|six|seven|eight|[1-8]) workshops?)", text, re.I)
        if match:
            word = (match[1] or match[2]).lower()
            numbers = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
                       "一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8}
            out["num_workshop_allowed"] = int(word) if word.isdigit() else numbers[word]
        elif text.lower() in ("取消刚才的排除", "清除排除", "clear exclusions"):
            out["exclusion"] = []
        elif re.fullmatch(r"(?:不要(?:用)?|排除|exclude |do not use )\s*W0*\d+", text, re.I):
            wid = "W" + str(int(re.search(r"\d+$", text)[0]))
            out["exclusion"] = sorted(set(out["exclusion"]) | {wid})
        elif re.fullmatch(r"(?:恢复|unexclude )\s*W0*\d+", text, re.I):
            wid = "W" + str(int(re.search(r"\d+$", text)[0]))
            out["exclusion"] = [w for w in out["exclusion"] if w != wid]
        elif text.lower() in ("最快", "最低成本", "最低缺陷", "平衡", "fastest", "cheapest", "lowest defects", "hybrid"):
            out["objective"] = {"最快":"min_delay","fastest":"min_delay","最低成本":"min_cost","cheapest":"min_cost",
                                "最低缺陷":"min_defects","lowest defects":"min_defects","平衡":"hybrid","hybrid":"hybrid"}[text.lower()]
        elif text.lower() in ("取消指定工坊", "clear preferred workshop"):
            out["preferred_workshop"] = None
        elif text.lower() in ("必须准时", "must arrive on time", "允许迟交", "allow late delivery"):
            out["deadline_required"] = text.lower() in ("必须准时", "must arrive on time")
        else:
            return None, "UNSUPPORTED_REPLY"
    if draft["order_id"] and out["order_id"] != draft["order_id"]:
        return None, "ORDER_SWITCH_REQUIRES_NEW_SESSION"
    out["missing_fields"] = [] if out["order_id"] else ["order_id"]
    out["parse_status"] = "needs_clarification" if out["missing_fields"] or out["ambiguities"] else "ok"
    return out, None


def session_turn(session_id, *, expected_version, request_id, action="message", message="",
                 db_path=None, database=None, actor=None):
    if (not _identifier(session_id) or not _identifier(request_id) or type(expected_version) is not int
            or expected_version < 0 or not isinstance(action, str) or action not in ("message", "replace", "confirm", "close")
            or not isinstance(message, str) or len(message) > 10000
            or (action in ("message", "replace") and not message.strip())
            or (action in ("confirm", "close") and message != "")
            or (actor is not None and (not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 120))):
        return _error("INVALID_ARGUMENT")
    identity = [SESSION_VERSION, session_id, expected_version, request_id, action, message]
    if actor is not None:
        identity.append(actor)
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    db = database
    try:
        db = db or Database(db_path or ":memory:")
        cached = _cached(db.connection, request_id, fingerprint)
        if cached:
            return cached
        snapshot = _snapshot(db.connection, session_id)
        if not snapshot:
            return _error("SESSION_NOT_FOUND")
        if snapshot["state"] == "CLOSED":
            return _error("SESSION_CLOSED")
        if snapshot["version"] != expected_version:
            return _error("SESSION_VERSION_CONFLICT")
        as_of = date.fromisoformat(snapshot["as_of_date"])
        draft, issue = snapshot["draft"], None
        telemetry = {"backend": "session_commands", "schema_version": SESSION_VERSION, "source_request_id": request_id}
        if action in ("message", "replace"):
            if expected_version == 0 or action == "replace":
                outcome = parse_with_telemetry(message, backend=snapshot["backend"], reference_date=as_of)
                telemetry = outcome.telemetry
                if outcome.error:
                    issue = "PARSER_ERROR"
                elif outcome.parsed.parse_status == "invalid":
                    issue = "INVALID_REQUEST"
                elif draft["order_id"] and outcome.parsed.order_id != draft["order_id"]:
                    issue = "ORDER_SWITCH_REQUIRES_NEW_SESSION"
                else:
                    draft = outcome.parsed.to_dict()
            else:
                patched, issue = _patch(message, draft)
                if patched:
                    draft = patched
        # Parsing/network I/O is outside the write lock. Version/key are checked
        # again before a draft or any production record can change.
        with db.transaction() as connection:
            cached = _cached(connection, request_id, fingerprint)
            if cached:
                return cached
            current = _snapshot(connection, session_id)
            if current["version"] != expected_version:
                return _error("SESSION_VERSION_CONFLICT")
            if current["state"] == "CLOSED":
                return _error("SESSION_CLOSED")
            trace = {"db_changes": []}
            blockers = list(current["blockers"]) if action == "confirm" else []
            reviewed = current["reviewed_order_version"]
            state = current["state"]
            preview = None
            parsed = ParseResult(**draft)
            if action == "close":
                result = {**terminal("CLOSED", "SESSION_CLOSED", "Session closed without allocation."), "success": True}
                state = "CLOSED"
            elif issue:
                blockers = [issue]
                result = terminal("CLARIFY", issue, REPLY_HELP)
                state = "AWAITING_CLARIFICATION"
            elif action == "confirm" and blockers:
                result = terminal("CLARIFY", "UNRESOLVED_CLARIFICATION", REPLY_HELP)
            else:
                preview = _decide(connection, parsed, current["objective"], as_of, trace)
                order_version = trace.get("order", {}).get("version")
                if action == "confirm" and order_version != reviewed:
                    result = terminal("REFUSE", "ORDER_VERSION_CONFLICT", "The order changed. Revise or replace the request to review it again.")
                    blockers = ["ORDER_VERSION_CONFLICT"]
                    state = "AWAITING_CLARIFICATION"
                elif action == "confirm":
                    result = preview
                    if result["success"]:
                        state = "CLOSED"
                    else:
                        blockers = result["reason_codes"]
                        state = "AWAITING_CLARIFICATION"
                elif preview["success"]:
                    reviewed = order_version
                    result = {**preview, "decision_status": "REVIEW", "explanation": preview["message"],
                              "message": "Draft updated. Review the recommendation and accept to allocate."}
                    state = "ACTIVE"
                else:
                    reviewed = order_version
                    blockers = parsed.missing_fields + parsed.ambiguities or preview["reason_codes"]
                    result = {**preview, "message": preview["message"] + " " + REPLY_HELP}
                    state = "AWAITING_CLARIFICATION"
            response = {"request_id": request_id, "session_id": session_id, "session_version": SESSION_VERSION,
                        "raw_message": message, "parsed": draft, "parser_telemetry": telemetry,
                        "trace": trace, "result": result, "replayed": False,
                        "committed": action == "confirm" and result["success"]}
            telemetry["field_sources"] = {"base_session_version": expected_version, "action": action,
                                           "merged_draft": draft, "issue": issue}
            outcome = ParserOutcome(parsed, telemetry)
            _record(connection, request_id, fingerprint, message, outcome, response)
            if actor is not None:
                connection.execute("INSERT INTO request_actors VALUES (?,?)", (request_id, actor))
            connection.execute("UPDATE requests SET session_id=? WHERE request_id=?", (session_id, request_id))
            if response["committed"]:
                _apply(connection, request_id, result, trace, as_of)
            now = utc_now()
            connection.execute("""UPDATE sessions SET state=?,version=version+1,draft_json=?,blockers_json=?,
                reviewed_order_version=?,updated_at=? WHERE session_id=?""",
                (state, json.dumps(draft), json.dumps(blockers), reviewed, now, session_id))
            for offset, role, content in ((1, "user", message or action), (2, "assistant", result["message"])):
                connection.execute("INSERT INTO session_messages VALUES (?,?,?,?,?,?,?)",
                                   (session_id, expected_version * 2 + offset, request_id, role, action, content, now))
            response["session"] = _snapshot(connection, session_id)
            connection.execute("UPDATE requests SET response_json=? WHERE request_id=?", (json.dumps(response), request_id))
            return response
    except (sqlite3.Error, OSError, ValueError):
        # Draft, messages, request audit and production writes all roll back.
        return {**_error("DB_ERROR", "Save failed and the transaction was rolled back. Retry with the same request ID."), "request_id": request_id}
    finally:
        if database is None and db:
            db.close()
