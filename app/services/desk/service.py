"""Read-model facade for dashboard, workshops, audit and history."""
from app.services.desk import queries as desk_mod
from app.db.database import Database
from app.services.desk.queries import history


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
