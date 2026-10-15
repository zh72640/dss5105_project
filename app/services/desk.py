"""Read-model facade for dashboard, workshops, audit and history."""
import json
from app.services import read_models as desk_mod
from app.db.database import Database


def dashboard(db_path, as_of):
    return desk_mod.dashboard(db_path, as_of)


def workshops(db_path, as_of, *, query="", status="", category=""):
    with Database(db_path) as db:
        items = desk_mod.workshops(db.connection, as_of)
    items = [w for w in items if (not query or query.casefold() in (w["workshop_id"] + " " + w["name"]).casefold())
             and (not status or w["status"] == status) and (not category or category in w["makes"])]
    return {"items": items, "business_date": as_of.isoformat()}


def audit(db_path, **kwargs):
    return desk_mod.audit(db_path, **kwargs)


def audit_csv(records):
    return desk_mod.audit_csv(records)


def history(db_path, *, limit=30):
    with Database(db_path) as db:
        rows = db.connection.execute(
            "SELECT request_id,request_date_time,status,response_json FROM requests "
            "ORDER BY request_date_time DESC LIMIT ?", (limit,)).fetchall()
        return [{"request_id": r["request_id"], "time": r["request_date_time"], "status": r["status"],
                 "order_id": (json.loads(r["response_json"]).get("parsed") or
                              json.loads(r["response_json"]).get("event") or {}).get("order_id")} for r in rows]
