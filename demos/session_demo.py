"""Repeatable multi-turn demonstration using one isolated persistent database."""
import json
import tempfile
from pathlib import Path
from app.db.database import Database
from app.lifecycle import inspect_order
from app.sessions import create_session, inspect_session, session_turn


def run():
    with tempfile.TemporaryDirectory(prefix="sweaterco-session-") as directory:
        path = Path(directory) / "session.sqlite3"
        create_session(session_id="demo", db_path=path)
        messages = ["Allocate cheapest; exclude W03.", "ORD-045", "改成两个工坊", "不要 W6", "取消刚才的排除", "不要 W3"]
        turns = [session_turn("demo", expected_version=i, request_id=f"demo-{i}", message=message, db_path=path)
                 for i, message in enumerate(messages)]
        before = inspect_order("ORD-045", db_path=path)
        final = session_turn("demo", expected_version=len(messages), request_id="demo-confirm", action="confirm", db_path=path)
        replay = session_turn("demo", expected_version=len(messages), request_id="demo-confirm", action="confirm", db_path=path)
        after = inspect_order("ORD-045", db_path=path)
        create_session(session_id="isolated", db_path=path)
        isolated = inspect_session("isolated", db_path=path)
        with Database(path) as db:
            foreign_keys_ok = not list(db.connection.execute("PRAGMA foreign_key_check"))
        verified = (before["state"] == "READY" and final["committed"] and replay["replayed"]
                    and after["version"] == 1 and isolated["draft"]["order_id"] is None and foreign_keys_ok
                    and final["parsed"]["exclusion"] == ["W3"] and final["parsed"]["num_workshop_allowed"] == 2)
        return {"verified": verified, "draft_only_before_confirmation": before["state"] == "READY",
                "replay_is_idempotent": replay["replayed"], "isolated_session_empty": isolated["draft"]["order_id"] is None,
                "foreign_keys_ok": foreign_keys_ok, "turns": turns, "confirmation": final, "order_after": after}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["verified"] else 1)
