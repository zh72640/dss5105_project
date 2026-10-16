"""Persistent clarification commands; print JSON for scripts and demonstrations."""
import argparse
import json
from datetime import date
from pathlib import Path
from app.sessions import create_session, inspect_session, session_turn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runtime/dispatch.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--session-id", required=True)
    create.add_argument("--objective", default="min_delay", choices=("min_delay", "min_cost", "min_defects", "hybrid"))
    from app.agent.deepseek_client import default_backend
    create.add_argument("--backend", default=default_backend(), choices=("offline", "llm", "deepseek"))
    create.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 4, 1))
    inspect = sub.add_parser("inspect")
    inspect.add_argument("session_id")
    turn = sub.add_parser("turn")
    turn.add_argument("session_id")
    turn.add_argument("--expected-version", type=int, required=True)
    turn.add_argument("--request-id", required=True)
    turn.add_argument("--action", choices=("message", "replace", "confirm", "close"), default="message")
    turn.add_argument("--message", default="")
    args = vars(parser.parse_args())
    command, path = args.pop("command"), args.pop("db")
    if command == "create":
        result = create_session(**args, db_path=path)
    elif command == "inspect":
        result = inspect_session(**args, db_path=path)
        if result is None:
            print(json.dumps({"error": "SESSION_NOT_FOUND"}))
            return 1
    else:
        result = session_turn(**args, db_path=path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("result", {}).get("decision_status")
    return 1 if status in ("ERROR", "REFUSE", "DECLINE", "ESCALATE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
