"""Fresh temporary database each run: repeatable demo with no runtime data deletion."""
import argparse
import json
import tempfile
from pathlib import Path
from app.db.database import Database
from app.pipeline import process_request

DEMO = "Allocate ORD-045 using the cheapest available workshops. Do not use W03 and use at most two workshops."


def run(backend="offline"):
    with tempfile.TemporaryDirectory(prefix="sweaterco-week6-") as directory:
        path = Path(directory) / "demo.sqlite3"
        first = process_request(DEMO, request_id="week6-demo-1", backend=backend, db_path=path)
        replay = process_request(DEMO, request_id="week6-demo-1", backend=backend, db_path=path)
        with Database(path) as db:
            tables = ("orders", "workshops", "requests", "request_parsing_history", "working_order", "decision_log", "unassigned_order")
            counts = {t: db.connection.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in tables}
        return {"first_request": first, "replay_is_idempotent": replay.get("replayed", False), "database_counts": counts}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--backend", choices=["offline", "llm"], default="offline")
    args = parser.parse_args(); result = run(args.backend)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["first_request"]["result"]["success"] and result["replay_is_idempotent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
