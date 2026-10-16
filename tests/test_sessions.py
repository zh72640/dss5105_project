import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.agent.parser import ParserOutcome
from app.db.database import Database, DB_VERSION
from app.lifecycle import inspect_order, process_event
from app.pipeline import process_request
from app.sessions import create_session, inspect_session, session_turn


class Sessions(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.close)
        create_session(session_id="session-a", database=self.db)
        self.counter = 0

    def turn(self, message="", action="message", **kwargs):
        self.counter += 1
        sid = kwargs.pop("session_id", "session-a")
        version = inspect_session(sid, database=self.db)["version"]
        return session_turn(sid, database=self.db, message=message, action=action,
                            **{"expected_version": version, "request_id": f"turn-{self.counter}", **kwargs})

    def order(self):
        return inspect_order("ORD-045", database=self.db)

    def test_clarify_edit_preview_confirm_and_replay(self):
        result = self.turn("Allocate cheapest; exclude W03.")
        self.assertEqual(result["session"]["state"], "AWAITING_CLARIFICATION")
        self.assertIn("order_id", result["session"]["blockers"])
        self.turn("ORD-045")
        self.turn("改成两个工坊")
        self.turn("不要 W6")
        self.turn("取消刚才的排除")
        result = self.turn("不要 W3")
        self.assertEqual(result["parsed"]["exclusion"], ["W3"])
        self.assertEqual(result["parsed"]["num_workshop_allowed"], 2)
        self.assertEqual(result["parsed"]["objective"], "min_cost")
        self.assertEqual(self.order()["state"], "READY")
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 0)
        version = result["session"]["version"]
        result = self.turn(action="confirm", request_id="confirm-once")
        self.assertTrue(result["committed"])
        self.assertEqual(result["session"]["state"], "CLOSED")
        before = self.order()
        replay = self.turn(action="confirm", request_id="confirm-once", expected_version=version)
        self.assertTrue(replay["replayed"])
        self.assertEqual(before, self.order())
        self.assertEqual(len(inspect_session("session-a", database=self.db)["messages"]), 14)
        self.assertTrue(inspect_session("session-a", database=self.db)["last_response"]["committed"])
        self.assertEqual(self.db.connection.execute("SELECT session_id FROM requests WHERE request_id='confirm-once'").fetchone()[0], "session-a")

    def test_session_isolation_and_switch_requires_new_session(self):
        create_session(session_id="session-b", database=self.db)
        self.turn("Allocate ORD-045 cheapest; exclude W3.")
        self.turn("Allocate fastest.", session_id="session-b")
        self.assertIsNone(inspect_session("session-b", database=self.db)["draft"]["order_id"])
        result = self.turn("ORD-109")
        self.assertEqual(result["result"]["reason_codes"], ["ORDER_SWITCH_REQUIRES_NEW_SESSION"])
        self.assertEqual(result["parsed"]["order_id"], "ORD-045")
        self.assertFalse(self.turn(action="confirm")["committed"])

    def test_unknown_reply_cannot_drop_constraints_or_confirm_old_draft(self):
        self.turn("Allocate ORD-045 cheapest.")
        result = self.turn("不要 W3，预算100元")
        self.assertEqual(result["result"]["reason_codes"], ["UNSUPPORTED_REPLY"])
        self.assertFalse(self.turn(action="confirm")["committed"])
        self.assertEqual(self.order()["state"], "READY")
        self.turn("Allocate ORD-045 fastest; exclude W6.", action="replace")
        self.assertTrue(self.turn(action="confirm")["committed"])
        self.assertNotEqual(self.order()["allocations"][0]["workshop_id"], "W6")

    def test_ambiguous_initial_request_requires_replacement(self):
        self.turn("Allocate ORD-045 cheapest and fastest.")
        r = self.turn("改成两个工坊")
        self.assertIn("conflicting_objective", r["session"]["blockers"])
        self.assertFalse(self.turn(action="confirm")["committed"])
        self.turn("Allocate ORD-045 fastest.", action="replace")
        self.assertTrue(self.turn(action="confirm")["committed"])

    def test_unknown_exclusion_and_remove(self):
        self.turn("Allocate ORD-045 cheapest.")
        self.assertIn("UNKNOWN_EXCLUDED_WORKSHOP", self.turn("不要 W99")["session"]["blockers"])
        self.assertFalse(self.turn(action="confirm")["committed"])
        self.turn("恢复 W99")
        self.assertTrue(self.turn(action="confirm")["committed"])

    def test_close_and_global_idempotency_conflicts(self):
        self.turn("Allocate ORD-045.", request_id="same")
        self.assertEqual(self.turn("最快", request_id="same")["result"]["reason_codes"], ["IDEMPOTENCY_CONFLICT"])
        r = process_request("Allocate ORD-109.", request_id="same", database=self.db, backend="offline")
        self.assertEqual(r["result"]["reason_codes"], ["IDEMPOTENCY_CONFLICT"])
        self.turn(action="close")
        self.assertEqual(self.turn("最快")["result"]["reason_codes"], ["SESSION_CLOSED"])
        self.assertEqual(self.order()["state"], "READY")

    def test_external_order_change_requires_new_review(self):
        self.turn("Allocate ORD-045 to Nimble Needle.")
        process_request("Allocate ORD-045 to Nimble Needle.", database=self.db, backend="offline")
        process_event("complete", "ORD-045", database=self.db, actor="tester", reason="partial",
                      event_id="partial", expected_version=1, workshop_id="W6", pieces=50)
        process_event("cancel", "ORD-045", database=self.db, actor="tester", reason="cancel",
                      event_id="cancel", expected_version=2)
        r = self.turn(action="confirm")
        self.assertEqual(r["result"]["reason_codes"], ["ORDER_VERSION_CONFLICT"])
        self.assertEqual(self.order()["state"], "READY")
        self.turn("最快")
        r = self.turn(action="confirm")
        self.assertEqual(sum(p["pieces"] for p in r["result"]["allocation"]), 100)
        self.assertEqual(self.order()["completed_pieces"], 50)

    def test_audit_failure_rolls_back_draft_allocation_and_retry(self):
        self.turn("Allocate ORD-045.")
        before = inspect_session("session-a", database=self.db)
        queues = list(map(tuple, self.db.connection.execute("SELECT * FROM workshop_queue")))
        self.db.connection.execute("""CREATE TRIGGER fail_message BEFORE INSERT ON session_messages
            BEGIN SELECT RAISE(ABORT,'injected'); END""")
        r = self.turn(action="confirm", request_id="retry")
        self.assertEqual(r["result"]["reason_codes"], ["DB_ERROR"])
        self.assertEqual(before, inspect_session("session-a", database=self.db))
        self.assertEqual(queues, list(map(tuple, self.db.connection.execute("SELECT * FROM workshop_queue"))))
        self.assertEqual(self.order()["state"], "READY")
        self.db.connection.execute("DROP TRIGGER fail_message")
        self.assertTrue(self.turn(action="confirm", request_id="retry")["committed"])

    def test_invalid_inputs_and_create_replay(self):
        self.assertTrue(create_session(session_id="session-a", database=self.db)["replayed"])
        self.assertIn("IDEMPOTENCY_CONFLICT", create_session(session_id="session-a", objective="min_cost", database=self.db)["result"]["reason_codes"])
        for invalid in ({"expected_version": True}, {"request_id": []}, {"action": []}, {"message": ""},
                        {"action": "confirm", "message": "extra constraint"}):
            args = {"expected_version": 0, "request_id": "bad", "message": "ORD-045", **invalid}
            self.assertEqual(session_turn("session-a", database=self.db, **args)["result"]["reason_codes"], ["INVALID_ARGUMENT"])
        self.assertEqual(inspect_session("session-a", database=self.db)["version"], 0)

    def test_restart_and_concurrent_confirm(self):
        for same_key in (True, False):
            with self.subTest(same_key=same_key), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "session.sqlite3"
                create_session(session_id="s", db_path=path)
                session_turn("s", expected_version=0, request_id="draft", message="Allocate ORD-045.", db_path=path)
                # New connections simulate independent clients and process restart.
                def confirm(key):
                    return session_turn("s", expected_version=1, request_id=key, action="confirm", db_path=path)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(confirm, ["c1", "c1" if same_key else "c2"]))
                self.assertEqual(sum(bool(r.get("committed")) and not r["replayed"] for r in results), 1)
                self.assertEqual(inspect_session("s", db_path=path)["version"], 2)
                with Database(path) as db:
                    self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 1)
                    self.assertEqual(list(db.connection.execute("PRAGMA foreign_key_check")), [])

    def test_parser_failure_is_audited_and_cannot_confirm(self):
        create_session(session_id="online", backend="llm", database=self.db)
        failed = ParserOutcome(None, {"backend":"llm","attempts":[{"error":"gemini_http_429"}]}, "gemini_http_429")
        with patch("app.sessions.parse_with_telemetry", return_value=failed) as parse:
            r = self.turn("Allocate ORD-045.", session_id="online")
        self.assertEqual(parse.call_args.kwargs["backend"], "llm")
        self.assertEqual(r["session"]["blockers"], ["PARSER_ERROR"])
        self.assertIsNone(r["parsed"]["order_id"])
        self.assertFalse(self.turn(action="confirm", session_id="online")["committed"])
        self.assertEqual(self.order()["state"], "READY")

    def test_competing_edits_and_cross_session_key_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edits.sqlite3"
            create_session(session_id="s", db_path=path)
            session_turn("s", expected_version=0, request_id="initial", message="Allocate ORD-045.", db_path=path)
            def edit(message):
                return session_turn("s", expected_version=1, request_id=message, message=message, db_path=path)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(edit, ["fastest", "cheapest"]))
            self.assertEqual(sum("session" in r for r in results), 1)
            self.assertEqual(sum(r["result"]["reason_codes"] == ["SESSION_VERSION_CONFLICT"] for r in results), 1)
            self.assertEqual(inspect_session("s", db_path=path)["version"], 2)
            create_session(session_id="other", db_path=path)
            r = session_turn("other", expected_version=0, request_id="initial", message="Allocate ORD-045.", db_path=path)
            self.assertEqual(r["result"]["reason_codes"], ["IDEMPOTENCY_CONFLICT"])
            self.assertEqual(inspect_session("other", db_path=path)["version"], 0)

    def test_v2_migration_preserves_business_data_and_rolls_back_on_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "old.sqlite3"
                with Database(path) as db:
                    process_request("Allocate ORD-045.", database=db, backend="offline")
                    before = inspect_order("ORD-045", database=db)
                    for table in ("login_sessions", "desk_users", "request_actors"):
                        db.connection.execute("DROP TABLE " + table)
                    db.connection.execute("DROP TABLE session_messages")
                    db.connection.execute("DROP TABLE sessions")
                    db.connection.execute("DROP INDEX requests_session_idx")
                    db.connection.execute("DELETE FROM schema_migrations WHERE version>=3")
                    if fail:
                        db.connection.execute("""CREATE TRIGGER reject_sessions BEFORE INSERT ON schema_migrations
                            WHEN NEW.version=3 BEGIN SELECT RAISE(ABORT,'fail'); END""")
                if fail:
                    with self.assertRaises(sqlite3.DatabaseError):
                        Database(path)
                    with closing(sqlite3.connect(path)) as connection:
                        self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 2)
                        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='sessions'").fetchone())
                else:
                    with Database(path) as db:
                        self.assertEqual(before, inspect_order("ORD-045", database=db))
                        self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], DB_VERSION)
