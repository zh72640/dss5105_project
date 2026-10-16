import argparse
import json
import os
from datetime import date
from pathlib import Path
from .pipeline import process_request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/dispatch_requests.txt"


def request_text(request_id):
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.startswith(request_id + " "):
            return line
    raise SystemExit(f"Unknown request: {request_id}")


def main():
    parser = argparse.ArgumentParser(description="SweaterCo single-message dispatch MVP v0.1")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--request", help="Dataset label, e.g. R09 (not the idempotency key)")
    source.add_argument("--message", help="Complete natural-language message")
    parser.add_argument("--objective", default="min_delay", choices=["min_delay", "min_lateness", "fastest_turnaround", "min_defects", "min_cost", "hybrid"])
    parser.add_argument("--db", default=str(ROOT / "runtime/dispatch.sqlite3"), help="Use :memory: for an isolated run")
    parser.add_argument("--request-id", help="Reuse this key only when retrying identical input")
    from app.agent.deepseek_client import default_backend
    parser.add_argument("--backend", choices=["offline", "llm", "deepseek"], default=default_backend())
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 4, 1))
    args = parser.parse_args()
    payload = process_request(args.message if args.message is not None else request_text(args.request or "R09"),
        args.objective, db_path=args.db, request_id=args.request_id, backend=args.backend, as_of=args.as_of)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if payload["result"]["decision_status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
