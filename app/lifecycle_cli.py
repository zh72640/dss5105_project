"""Inspect production or submit an explicit event using a reviewed order version."""
import argparse
import json
from datetime import date
from pathlib import Path

from app.lifecycle import ACTIONS, inspect_order, process_event
from app.schemas.parser_schema import OBJECTIVES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", *ACTIONS])
    parser.add_argument("order_id")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runtime/dispatch.sqlite3"))
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--event-id")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 4, 1))
    parser.add_argument("--workshop-id")
    parser.add_argument("--pieces", type=int)
    parser.add_argument("--objective", choices=OBJECTIVES, default="min_delay")
    parser.add_argument("--exclude", action="append")
    parser.add_argument("--max-workshops", type=int, default=1)
    parser.add_argument("--preferred-workshop")
    parser.add_argument("--deadline-required", action="store_true")
    args = parser.parse_args()
    if args.action == "inspect":
        result = inspect_order(args.order_id, db_path=args.db)
        print(json.dumps(result or {"error": "ORDER_NOT_FOUND"}, indent=2, ensure_ascii=False))
        return 0 if result else 1
    if any(value is None for value in (args.actor, args.reason, args.expected_version, args.event_id)):
        parser.error("events require --actor, --reason, --expected-version and --event-id")
    result = process_event(args.action, args.order_id, actor=args.actor, reason=args.reason,
                           expected_version=args.expected_version, event_id=args.event_id, db_path=args.db,
                           as_of=args.as_of, workshop_id=args.workshop_id, pieces=args.pieces,
                           objective=args.objective, exclusion=args.exclude, max_workshops=args.max_workshops,
                           preferred_workshop=args.preferred_workshop, deadline_required=args.deadline_required)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["result"]["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
