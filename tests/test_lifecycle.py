"""State, quantity, queue, audit and migration invariants for production events."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.db.database import Database, ROOT
from app.lifecycle import inspect_order, process_event, snapshot
from app.pipeline import process_request


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.close)

    def allocate(self, message="Allocate ORD-045 to Nimble Needle.", **kwargs):
        return process_request(message, database=self.db, backend="offline", **kwargs)

    def state(self, order_id="ORD-045"):
        return snapshot(self.db.connection, order_id)

    def event(self, action, order_id="ORD-045", **kwargs):
        args = dict(actor="test-operator", reason="Production update", event_id=str(uuid4()),
                    expected_version=self.state(order_id)["version"] if self.state(order_id) else 0)
        args.update(kwargs)
        return process_event(action, order_id, database=self.db, **args)

    def business(self):
        tables = ("orders", "working_order", "workshop_queue", "completed_order", "lapsed_order", "unassigned_order")
        return {t: [tuple(r) for r in self.db.connection.execute("SELECT * FROM " + t)] for t in tables}

    def assert_consistent(self):
        for q in self.db.connection.execute("SELECT * FROM workshop_queue"):
            total = self.db.connection.execute("SELECT COALESCE(SUM(queue_remaining_days),0) FROM working_order WHERE workshop_id=?",
                                               (q["workshop_id"],)).fetchone()[0]
            self.assertAlmostEqual(q["current_queue_days"], q["baseline_queue_days"] + total)
        for o in self.db.connection.execute("SELECT * FROM orders"):
            active = self.db.connection.execute("SELECT COALESCE(SUM(pieces-completed_pieces),0) FROM working_order WHERE order_id=?",
                                                (o["order_id"],)).fetchone()[0]
            if o["state"] == "WORKING":
                self.assertEqual(active + o["completed_pieces"], o["pieces"])
            else:
                self.assertEqual(active, 0)
            if o["state"] == "COMPLETED":
                self.assertEqual(o["completed_pieces"], o["pieces"])
        self.assertEqual(list(self.db.connection.execute("PRAGMA foreign_key_check")), [])

    def tearDown(self):
        self.assert_consistent()

    def test_partial_complete_cancel_and_allocate_only_remaining(self):
        self.assertTrue(self.allocate()["result"]["success"])
        result = self.event("complete", workshop_id="W6", pieces=50)
        self.assertEqual(result["order"]["completed_pieces"], 50)
        self.assertEqual(result["order"]["state"], "WORKING")
        self.assertTrue(self.event("cancel")["result"]["success"])
        self.assertEqual(self.state()["state"], "READY")
        result = self.allocate()
        self.assertEqual(sum(p["pieces"] for p in result["result"]["allocation"]), 100)
        done = self.event("complete", workshop_id="W6", pieces=100)
        self.assertEqual(done["order"]["state"], "COMPLETED")
        self.assertEqual(done["order"]["version"], 5)
        self.assertEqual(self.allocate()["result"]["reason_codes"], ["ORDER_ALREADY_COMPLETED"])

    def test_split_completion_does_not_complete_whole_order_early(self):
        allocated = self.allocate("Allocate ORD-093 fastest; at most two workshops.")
        parts = allocated["result"]["allocation"]
        self.assertEqual(len(parts), 2)
        first = self.event("complete", "ORD-093", workshop_id=parts[0]["workshop_id"], pieces=parts[0]["pieces"])
        self.assertEqual(first["order"]["state"], "WORKING")
        self.assertEqual(len(first["order"]["allocations"]), 1)
        second = self.event("complete", "ORD-093", workshop_id=parts[1]["workshop_id"], pieces=parts[1]["pieces"])
        self.assertEqual(second["order"]["state"], "COMPLETED")

    def test_cancel_replay_conflict_and_stale_version(self):
        self.allocate()
        first = self.event("cancel", event_id="cancel-1", expected_version=1)
        before = self.business()
        replay = self.event("cancel", event_id="cancel-1", expected_version=1)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["order"], replay["order"])
        self.assertEqual(self.event("lapse", event_id="cancel-1", expected_version=1)["result"]["reason_codes"], ["IDEMPOTENCY_CONFLICT"])
        self.assertEqual(self.event("lapse", expected_version=1)["result"]["reason_codes"], ["VERSION_CONFLICT"])
        self.assertEqual(before, self.business())

    def test_new_event_key_cannot_repeat_completion_with_stale_version(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=20, expected_version=1)
        r = self.event("complete", workshop_id="W6", pieces=20, expected_version=1)
        self.assertEqual(r["result"]["reason_codes"], ["VERSION_CONFLICT"])
        self.assertEqual(self.state()["completed_pieces"], 20)

    def test_bad_completion_and_unknown_order_leave_business_unchanged(self):
        self.allocate()
        before = self.business()
        self.assertEqual(self.event("complete", workshop_id="W6", pieces=151)["result"]["reason_codes"], ["COMPLETION_EXCEEDS_REMAINING"])
        self.assertEqual(self.event("complete", workshop_id="W1", pieces=1)["result"]["reason_codes"], ["ALLOCATION_NOT_FOUND"])
        self.assertEqual(self.event("lapse", "ORD-999")["result"]["reason_codes"], ["ORDER_NOT_FOUND"])
        self.assertEqual(before, self.business())

    def test_reassign_preserves_completed_pieces_and_releases_old_queue(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=50)
        result = self.event("reassign", preferred_workshop="W8", objective="min_cost")
        self.assertTrue(result["result"]["success"])
        self.assertEqual(result["order"]["version"], 3)
        self.assertEqual([(r["workshop_id"], r["pieces"]) for r in result["order"]["allocations"]], [("W8", 100)])
        self.assertAlmostEqual(self.db.connection.execute("SELECT current_queue_days FROM workshop_queue WHERE workshop_id='W6'").fetchone()[0], 1.)

    def test_infeasible_reassign_restores_every_business_table(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=30)
        before = self.business()
        for options in ({"preferred_workshop": "W7"}, {"exclusion": [f"W{i}" for i in range(1, 9)]},
                        {"preferred_workshop": "W99"}, {"exclusion": ["W99"]}):
            result = self.event("reassign", **options)
            self.assertFalse(result["result"]["success"])
            self.assertEqual(before, self.business())
            self.assertEqual(result["trace"]["db_changes"], [])

    def test_infeasible_hard_deadline_reassign_restores_assignment(self):
        self.allocate("Allocate ORD-093 fastest.")
        before = self.business()
        r = self.event("reassign", "ORD-093", deadline_required=True)
        self.assertEqual(r["result"]["reason_codes"], ["DEADLINE_INFEASIBLE"])
        self.assertEqual(before, self.business())

    def test_lapse_working_and_ready_orders_and_terminal_protection(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=10)
        r = self.event("lapse")
        self.assertEqual(r["order"]["state"], "LAPSED")
        self.assertEqual(r["order"]["completed_pieces"], 10)
        self.assertEqual(self.event("reassign")["result"]["reason_codes"], ["INVALID_ORDER_STATE"])
        self.assertEqual(self.allocate()["result"]["reason_codes"], ["ORDER_ALREADY_LAPSED"])
        self.assertTrue(self.event("lapse", "ORD-109")["result"]["success"])

    def test_lapse_unassigned_cleans_retry_record(self):
        self.allocate("Allocate ORD-073 to FreshStart.")
        self.assertEqual(self.state("ORD-073")["state"], "UNASSIGNED")
        self.assertTrue(self.event("lapse", "ORD-073")["result"]["success"])
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM unassigned_order").fetchone()[0], 0)

    def test_fifo_elapsed_queue_cancel_preserves_later_order(self):
        self.allocate()
        self.allocate("Allocate ORD-109 to Nimble Needle.")
        later = self.state("ORD-109")["allocations"][0]
        # One baseline day and one production day elapse before cancellation.
        self.event("cancel", as_of=date(2026, 4, 3))
        q = self.db.connection.execute("SELECT current_queue_days FROM workshop_queue WHERE workshop_id='W6'").fetchone()[0]
        self.assertAlmostEqual(q, later["pieces"] / 130)
        self.assertEqual(self.state("ORD-109")["state"], "WORKING")

    def test_forecast_decay_and_confirmed_completion_do_not_double_release(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=50, as_of=date(2026, 4, 3))
        remaining = self.state()["allocations"][0]["queue_remaining_days"]
        self.assertAlmostEqual(remaining, 150 / 130 - 1)
        self.event("complete", workshop_id="W6", pieces=100, as_of=date(2026, 4, 3))
        q = self.db.connection.execute("SELECT current_queue_days FROM workshop_queue WHERE workshop_id='W6'").fetchone()[0]
        self.assertEqual(q, 0)

    def test_expired_forecast_is_not_confirmed_completion(self):
        self.allocate()
        self.event("complete", workshop_id="W6", pieces=1, as_of=date(2026, 5, 1))
        self.assertEqual(self.state()["state"], "WORKING")
        self.assertEqual(self.state()["completed_pieces"], 1)
        self.assertEqual(self.state()["allocations"][0]["queue_remaining_days"], 0)

    def test_queue_fault_rolls_back_and_records_failed_event(self):
        self.allocate()
        before = self.business()
        self.db.connection.execute("""CREATE TRIGGER fail_queue BEFORE UPDATE ON workshop_queue BEGIN
            SELECT RAISE(ABORT,'injected failure'); END""")
        r = self.event("cancel")
        self.assertEqual(r["result"]["reason_codes"], ["DB_ERROR"])
        self.assertEqual(before, self.business())
        self.assertEqual(self.db.connection.execute("SELECT applied FROM lifecycle_events").fetchone()[0], 0)

    def test_audit_fault_rolls_back_successful_business_change(self):
        self.allocate()
        before = self.business()
        self.db.connection.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON lifecycle_events BEGIN
            SELECT RAISE(ABORT,'injected audit failure'); END""")
        r = self.event("complete", workshop_id="W6", pieces=150, event_id="audit-fails")
        self.assertFalse(r["error_logged"])
        self.assertEqual(before, self.business())
        self.assertIsNone(self.db.connection.execute("SELECT * FROM requests WHERE request_id='audit-fails'").fetchone())

    def test_reassign_insert_failure_restores_old_assignment_and_queue(self):
        self.allocate()
        before = self.business()
        self.db.connection.execute("""CREATE TRIGGER fail_reassign BEFORE INSERT ON working_order BEGIN
            SELECT RAISE(ABORT,'injected reassign failure'); END""")
        r = self.event("reassign", preferred_workshop="W8")
        self.assertEqual(r["result"]["reason_codes"], ["DB_ERROR"])
        self.assertEqual(before, self.business())

    def test_split_partial_completion_then_reassign_conserves_quantity(self):
        r = self.allocate("Allocate ORD-093 fastest; at most two workshops.")
        part = r["result"]["allocation"][0]
        self.event("complete", "ORD-093", workshop_id=part["workshop_id"], pieces=10)
        r = self.event("reassign", "ORD-093", max_workshops=2, exclusion=[part["workshop_id"]])
        self.assertTrue(r["result"]["success"])
        self.assertEqual(sum(a["pieces"] for a in r["order"]["allocations"]), 90)
        self.assertEqual(r["order"]["completed_pieces"], 10)

    def test_missing_queue_blocks_cancellation_without_losing_assignment(self):
        self.allocate()
        queue = tuple(self.db.connection.execute("SELECT * FROM workshop_queue WHERE workshop_id='W6'").fetchone())
        self.db.connection.execute("DELETE FROM workshop_queue WHERE workshop_id='W6'")
        before = self.business()
        r = self.event("cancel")
        self.assertEqual(r["result"]["reason_codes"], ["QUEUE_DATA_MISSING"])
        self.assertEqual(before, self.business())
        self.db.connection.execute("INSERT INTO workshop_queue VALUES (?,?,?,?)", queue)

    def test_backward_date_is_rejected_and_audited(self):
        self.allocate()
        before = self.business()
        r = self.event("cancel", as_of=date(2026, 3, 31))
        self.assertEqual(r["result"]["reason_codes"], ["QUEUE_DATE_REWIND"])
        self.assertEqual(before, self.business())

    def test_audit_preserves_removed_allocation_actor_reason_and_decision(self):
        self.allocate()
        original = self.state()
        self.event("cancel", event_id="audit-ok", actor="operator-a", reason="Workshop unavailable")
        row = self.db.connection.execute("SELECT * FROM lifecycle_events WHERE event_id='audit-ok'").fetchone()
        self.assertEqual(json.loads(row["before_json"]), original)
        self.assertEqual(json.loads(row["after_json"])["allocations"], [])
        self.assertEqual(row["actor"], "operator-a")
        self.assertEqual(row["reason"], "Workshop unavailable")
        self.assertEqual(self.db.connection.execute("SELECT decision_status FROM decision_log WHERE request_id='audit-ok'").fetchone()[0], "CANCEL")
        self.assertEqual(inspect_order("ORD-045", database=self.db)["events"][0]["event_id"], "audit-ok")

    def test_invalid_inputs_are_rejected_before_writes(self):
        self.allocate()
        for kwargs in ({"actor": " "}, {"reason": ""}, {"expected_version": True}, {"event_id": []},
                       {"action": []}, {"workshop_id": "W6"}, {"objective": []}):
            args = {"action": "cancel", **kwargs}
            r = self.event(**args)
            self.assertEqual(r["result"]["reason_codes"], ["INVALID_ARGUMENT"])
        for pieces in (True, 0, -1, 2.5, "20"):
            self.assertEqual(self.event("complete", workshop_id="W6", pieces=pieces)["result"]["reason_codes"], ["INVALID_ARGUMENT"])
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM lifecycle_events").fetchone()[0], 0)

    def test_allocation_and_event_share_idempotency_namespace(self):
        self.allocate(request_id="shared")
        self.assertEqual(self.event("cancel", event_id="shared")["result"]["reason_codes"], ["IDEMPOTENCY_CONFLICT"])

    def test_concurrent_completions_same_key_and_stale_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "concurrent.sqlite3"
            process_request("Allocate ORD-045 to Nimble Needle.", db_path=path, backend="offline")
            def submit(key):
                return process_event("complete", "ORD-045", actor="operator", reason="Batch arrived", expected_version=1,
                                     event_id=key, db_path=path, workshop_id="W6", pieces=30)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(submit, ["same-event", "same-event"]))
            self.assertEqual(sum(r["replayed"] for r in results), 1)
            self.assertEqual(submit("different-event")["result"]["reason_codes"], ["VERSION_CONFLICT"])
            self.assertEqual(inspect_order("ORD-045", db_path=path)["completed_pieces"], 30)

    def test_concurrent_different_events_cannot_both_apply_same_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "competing.sqlite3"
            process_request("Allocate ORD-045 to Nimble Needle.", db_path=path, backend="offline")
            def submit(action):
                return process_event(action, "ORD-045", actor="operator", reason="Competing update", expected_version=1,
                                     event_id=action, db_path=path)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(submit, ["cancel", "lapse"]))
            self.assertEqual(sum(r["result"]["success"] for r in results), 1)
            self.assertEqual(sum(r["result"]["reason_codes"] == ["VERSION_CONFLICT"] for r in results), 1)


class MigrationTests(unittest.TestCase):
    def legacy(self, path):
        connection = sqlite3.connect(path)
        connection.executescript((ROOT / "app/db/migrations/001_initial.sql").read_text())
        connection.execute("INSERT INTO schema_migrations VALUES (1,'2026-04-01')")
        connection.execute("INSERT INTO orders VALUES ('ORD-045','Customer','Polo Shirt','TOPS',150,'2026-03-01','2026-04-09','IN_PROGRESS','WORKING')")
        connection.execute("INSERT INTO workshops VALUES ('W6','Nimble Needle',130,1,0.01,1.2,'TOPS','ACTIVE',NULL,'')")
        connection.execute("INSERT INTO requests VALUES ('old-request','2026-04-01','old-fingerprint','Allocate ORD-045.','ALLOCATE','{}','{}',NULL)")
        connection.execute("INSERT INTO working_order VALUES ('ORD-045','W6','old-request',150,3.15,180,'min_delay','2026-04-01')")
        connection.execute("INSERT INTO workshop_queue VALUES ('W6',?,'2026-04-03')", (150 / 130 - 1,))
        connection.commit()
        connection.close()

    def test_upgrade_preserves_old_queue_and_recovers_only_unelapsed_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v1.sqlite3"
            self.legacy(path)
            with Database(path) as db:
                row = db.connection.execute("SELECT * FROM working_order").fetchone()
                self.assertAlmostEqual(row["queue_remaining_days"], 150 / 130 - 1)
                self.assertEqual(row["capacity_at_assignment"], 130)
                self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 3)
                r = process_event("cancel", "ORD-045", actor="operator", reason="Migrated cancellation", expected_version=0,
                                  event_id="migration-event", database=db, as_of=date(2026, 4, 3))
                self.assertTrue(r["result"]["success"])
                self.assertAlmostEqual(db.connection.execute("SELECT current_queue_days FROM workshop_queue").fetchone()[0], 0)
            with Database(path) as db:
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 3)
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)

    def test_failed_upgrade_rolls_back_ddl_and_preserves_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v1.sqlite3"
            self.legacy(path)
            with sqlite3.connect(path) as connection:
                connection.execute("""CREATE TRIGGER reject_upgrade BEFORE INSERT ON schema_migrations
                    WHEN NEW.version=2 BEGIN SELECT RAISE(ABORT,'migration failure'); END""")
            with self.assertRaises(sqlite3.DatabaseError):
                Database(path)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 1)
                self.assertNotIn("version", [r[1] for r in connection.execute("PRAGMA table_info(orders)")])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM working_order").fetchone()[0], 1)

    def test_unknown_future_version_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            with Database(path) as db:
                db.connection.execute("INSERT INTO schema_migrations VALUES (99,'future')")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "unsupported_database_version"):
                Database(path)
