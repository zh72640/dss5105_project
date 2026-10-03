"""Production lifecycle on one temporary persistent database, with invariant checks."""
import json
import tempfile
from pathlib import Path
from app.db.database import Database
from app.lifecycle import inspect_order, process_event
from app.pipeline import process_request


def run():
    with tempfile.TemporaryDirectory(prefix="sweaterco-lifecycle-") as directory:
        path = Path(directory) / "lifecycle.sqlite3"
        steps = []
        steps.append(process_request("Allocate ORD-045 to Nimble Needle.", db_path=path, backend="offline", request_id="allocate-1"))

        def event(action, event_id, **kwargs):
            order = inspect_order("ORD-045", db_path=path)
            result = process_event(action, "ORD-045", actor="demo-operator", reason="Lifecycle acceptance demo",
                                   expected_version=order["version"], event_id=event_id, db_path=path, **kwargs)
            steps.append(result)
            if not result["result"]["success"]:
                raise AssertionError(result["result"])
            return result

        event("complete", "complete-50", workshop_id="W6", pieces=50)
        event("cancel", "cancel-remaining")
        steps.append(process_request("Allocate ORD-045 to Nimble Needle.", db_path=path, backend="offline", request_id="allocate-remaining"))
        reassigned = event("reassign", "reassign-100", preferred_workshop="W8")
        replay = process_event("reassign", "ORD-045", actor="demo-operator", reason="Lifecycle acceptance demo",
                               expected_version=reassigned["event"]["expected_version"], event_id="reassign-100", db_path=path,
                               preferred_workshop="W8")
        event("complete", "complete-100", workshop_id="W8", pieces=100)
        lapsed = process_event("lapse", "ORD-093", actor="demo-operator", reason="Customer no longer needs production",
                               expected_version=0, event_id="lapse-093", db_path=path)
        steps.append(lapsed)
        final = inspect_order("ORD-045", db_path=path)
        with Database(path) as db:
            queues = [dict(r) for r in db.connection.execute("SELECT * FROM workshop_queue ORDER BY workshop_id")]
            queue_consistent = all(abs(q["current_queue_days"] - q["baseline_queue_days"] -
                db.connection.execute("SELECT COALESCE(SUM(queue_remaining_days),0) FROM working_order WHERE workshop_id=?",
                                      (q["workshop_id"],)).fetchone()[0]) < 1e-8 for q in queues)
            audit_count = db.connection.execute("SELECT COUNT(*) FROM lifecycle_events").fetchone()[0]
            foreign_keys_ok = not list(db.connection.execute("PRAGMA foreign_key_check"))
        verified = (all(s["result"]["success"] for s in steps) and replay["replayed"] and
                    final["state"] == "COMPLETED" and final["completed_pieces"] == 150 and not final["allocations"] and
                    queue_consistent and foreign_keys_ok and audit_count == 5)
        return {"verified": verified, "steps": steps, "replayed": replay["replayed"], "final_order": final,
                "queues": queues, "queue_consistent": queue_consistent, "foreign_keys_ok": foreign_keys_ok,
                "lifecycle_event_count": audit_count}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["verified"] else 1)
