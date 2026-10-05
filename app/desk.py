"""Read models for the dispatch desk. No production state is changed here."""
import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timezone

from app.db.database import Database
from app.repositories.workshop_repository import get_all


def workshops(connection, as_of):
    active = {}
    for row in connection.execute("""SELECT workshop_id,order_id,pieces-completed_pieces AS remaining
        FROM working_order WHERE pieces>completed_pieces ORDER BY order_id"""):
        active.setdefault(row["workshop_id"], []).append({"order_id": row["order_id"], "remaining_pieces": row["remaining"]})
    return [{**asdict(w), "makes": sorted(w.makes), "orders": active.get(w.workshop_id, [])}
            for w in get_all(connection, as_of)]


def dashboard(db_path, as_of):
    with Database(db_path) as db:
        c = db.connection
        c.execute("BEGIN")
        orders = [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY due_date,order_id")]
        lookup = {r["order_id"]: r for r in orders}
        inbox, represented = [], set()
        for row in c.execute("""SELECT s.*, (SELECT m.content FROM session_messages m WHERE m.session_id=s.session_id
            AND m.role='user' ORDER BY m.sequence LIMIT 1) AS original_message FROM sessions s
            WHERE s.state!='CLOSED' ORDER BY s.updated_at DESC,s.session_id"""):
            draft = json.loads(row["draft_json"])
            oid = draft.get("order_id")
            represented.add(oid)
            order = lookup.get(oid, {})
            inbox.append({"session_id": row["session_id"], "order_id": oid,
                          "customer": order.get("customer"), "product": order.get("product"),
                          "due_date": order.get("due_date"), "pieces": order.get("pieces"),
                          "status": "CLARIFY" if row["state"] == "AWAITING_CLARIFICATION" and row["version"] else "PENDING",
                          "original_message": row["original_message"], "updated_at": row["updated_at"]})
        for order in orders:
            if order["state"] in ("READY", "UNASSIGNED") and order["order_id"] not in represented:
                inbox.append({**order, "session_id": None, "status": "PENDING", "original_message": None})
        today = datetime.now(timezone.utc).date().isoformat()
        allocated = c.execute("""SELECT COUNT(DISTINCT order_id) FROM decision_log
            WHERE decision_status='ALLOCATE' AND substr(created_at,1,10)=?""", (today,)).fetchone()[0]
        result = {"stats": {"pending": sum(r["status"] == "PENDING" for r in inbox),
                            "clarification": sum(r["status"] == "CLARIFY" for r in inbox),
                            "allocated_today": allocated,
                            "lapsed": sum(r["state"] == "LAPSED" for r in orders),
                            "assigned": sum(r["state"] == "WORKING" for r in orders),
                            "unallocated_orders": sum(r["state"] in ("READY", "UNASSIGNED") for r in orders)},
                  "inbox": inbox, "orders": orders, "workshops": workshops(c, as_of),
                  "business_date": as_of.isoformat(), "audit_date_utc": today}
        c.execute("COMMIT")
        return result


def _audit_record(row):
    response = json.loads(row["response_json"])
    result = response.get("result", {})
    event = response.get("event", {})
    approved = bool(result.get("success") and row["status"] in ("ALLOCATE", "REASSIGNED"))
    actor = row["actor"] or event.get("actor")
    return {"request_id": row["request_id"], "session_id": row["session_id"],
            "order_id": (response.get("parsed") or event).get("order_id") or row["order_id"],
            "status": row["status"], "timestamp": row["request_date_time"],
            "original_message": row["first_message"] or row["original_message"],
            "message_time": row["first_time"] or row["request_date_time"],
            "turn_message": row["original_message"], "parsed": response.get("parsed") or event,
            "result": result, "actor": actor, "approved": approved,
            "approved_by": actor if approved else None,
            "approval_timestamp": row["request_date_time"] if approved else None,
            "trace": response.get("trace", {})}


def audit(db_path, *, query="", status="", page=1, page_size=25, export=False, request_id=None):
    # Searches are literal substrings. Quotes and SQL wildcards have no special meaning.
    where, args = [], []
    if query:
        where.append("(instr(lower(COALESCE(d.order_id,p.parsed_order_id,'')),lower(?))>0 OR instr(lower(r.request_id),lower(?))>0)")
        args.extend([query, query])
    if status:
        where.append("r.status=?")
        args.append(status)
    if request_id:
        where.append("r.request_id=?")
        args.append(request_id)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with Database(db_path) as db:
        c = db.connection
        c.execute("BEGIN")
        joins = " FROM requests r LEFT JOIN decision_log d USING(request_id) LEFT JOIN request_parsing_history p USING(request_id)"
        total = c.execute("SELECT COUNT(*)" + joins + clause, args).fetchone()[0]
        sql = """SELECT r.*,COALESCE(d.order_id,p.parsed_order_id) AS order_id,a.actor,
            (SELECT content FROM session_messages WHERE session_id=r.session_id AND role='user' ORDER BY sequence LIMIT 1) AS first_message,
            (SELECT created_at FROM session_messages WHERE session_id=r.session_id AND role='user' ORDER BY sequence LIMIT 1) AS first_time
            """ + joins + " LEFT JOIN request_actors a USING(request_id)"
        sql += clause + " ORDER BY r.request_date_time DESC,r.request_id DESC"
        if not export and not request_id:
            sql += " LIMIT ? OFFSET ?"
            args.extend([page_size, (page - 1) * page_size])
        items = [_audit_record(r) for r in c.execute(sql, args)]
        c.execute("COMMIT")
        return {"items": items, "total": total, "page": page, "page_size": page_size}


def audit_csv(records):
    stream = io.StringIO(newline="")
    fields = ["request_id", "session_id", "order_id", "status", "original_message", "message_time",
              "turn_message", "parsed", "result", "actor", "approved", "approved_by", "approval_timestamp", "timestamp", "trace"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for record in records:
        output = {}
        for field in fields:
            value = record.get(field)
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else "" if value is None else str(value)
            # Neutralize formulas when a CSV is opened in spreadsheet software.
            output[field] = "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text
        writer.writerow(output)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
