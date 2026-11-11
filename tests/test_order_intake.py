"""Manual registration contracts, durable audit, replay and concurrent decisions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.settings import Settings
from app.core.security import set_password
from app.db.database import Database, DB_VERSION
from app.db.order_repository import get_order
from app.main import create_app
from app.schemas.order_intake import ORDER_FIELDS
from app.services import order_intake as intake
from app.services.chat import service as chat
from app.services.allocation.dispatch import seed_allocation


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "orders.sqlite3")
        with Database(self.path) as db:
            self.existing = get_order(db.connection, "ORD-045")
        self.facts = {field: self.existing[field] for field in ORDER_FIELDS}

    def check(self, facts=None, actor="alice", request_id=None):
        return intake.check({"request_id": request_id or str(uuid4()), "order": facts or self.facts},
                            actor=actor, db_path=self.path)

    def body(self, review, action=None, **kwargs):
        return {"request_id": str(uuid4()), "action": action or ("create" if review["match"] == "missing" else "update"),
                "expected_version": review["expected_version"], "reason": "Checked against the customer order sheet.",
                "confirmed_order_id": review["order_id"],
                "verified_fields": [d["field"] for d in review["differences"]], **kwargs}

    def decide(self, review, action=None, actor="alice", **kwargs):
        return intake.decide(review["review_id"], self.body(review, action, **kwargs), actor=actor, db_path=self.path)

    def order(self, order_id="ORD-045"):
        with Database(self.path) as db:
            return get_order(db.connection, order_id)

    def history(self, **kwargs):
        return intake.history(actor="alice", db_path=self.path, **kwargs)

    def test_missing_order_only_written_on_confirmation_and_available_in_chat(self):
        review = self.check({**self.facts, "order_id": "ORD-901"})
        self.assertEqual(review["match"], "missing")
        self.assertIsNone(self.order("ORD-901"))
        response, status = self.decide(review)
        self.assertEqual((status, response["outcome"]), (200, "CREATED"))
        order = self.order("ORD-901")
        self.assertEqual((order["state"], order["version"], order["completed_pieces"]), ("READY", 0, 0))
        preview = chat.create(owner="alice", request_id="manual-chat", db_path=self.path,
            as_of=date(2026, 4, 1), mode="offline", message="Allocate ORD-901.")
        self.assertFalse(preview["committed"])
        self.assertEqual(preview["session"]["task"]["draft"]["order_id"], "ORD-901")
        self.assertEqual(preview["session"]["recommendation"]["status"], "valid")

    def test_normalization_preserves_original_input_and_identical_order(self):
        raw = {**self.facts, "order_id": " ord-045 ", "customer": " " + self.facts["customer"] + " ",
               "category": self.facts["category"].lower()}
        review = self.check(raw)
        self.assertEqual(review["match"], "identical")
        self.assertEqual(review["submitted"], raw)
        self.assertEqual(review["differences"], [])
        self.assertEqual(self.order(), self.existing)
        self.assertEqual(self.history()["items"][0]["match"], "identical")

    def test_secondary_verification_updates_all_changed_fields_and_audits(self):
        facts = {**self.facts, "pieces": 180, "customer": "New customer", "due_date": "2026-12-31"}
        review = self.check(facts)
        self.assertEqual({d["field"] for d in review["differences"]}, {"pieces", "customer", "due_date"})
        self.assertEqual(self.order(), self.existing)
        response, status = self.decide(review)
        self.assertEqual((status, response["outcome"]), (200, "UPDATED"))
        self.assertEqual(self.order()["version"], self.existing["version"] + 1)
        record = self.history()["items"][0]
        self.assertEqual(record["decision"]["evidence"]["before"], self.existing)
        self.assertEqual(record["decision"]["evidence"]["after"], self.order())
        self.assertEqual(record["decision"]["evidence"]["proposed"], facts)
        self.assertEqual(record["decision"]["actor"], "alice")

    def test_rejection_preserves_proposal_reason_and_database_values(self):
        for facts in ({**self.facts, "pieces": 777}, {**self.facts, "order_id": "ORD-902"}):
            review = self.check(facts)
            response, status = self.decide(review, "reject", reason="Customer did not authorize this change.")
            self.assertEqual((status, response["outcome"]), (200, "REJECTED"))
            record = self.history(order_id=facts["order_id"])["items"][0]
            self.assertEqual(record["decision"]["reason"], "Customer did not authorize this change.")
            self.assertEqual(record["decision"]["evidence"]["proposed"], facts)
        self.assertEqual(self.order(), self.existing)
        self.assertIsNone(self.order("ORD-902"))

    def test_partial_or_wrong_secondary_verification_is_recorded_without_writes(self):
        for evidence in ({"verified_fields": []}, {"confirmed_order_id": "ORD-046"},
                         {"verified_fields": ["pieces", "pieces"]}, {"verified_fields": ["customer"]}):
            review = self.check({**self.facts, "pieces": 151})
            result, status = self.decide(review, **evidence)
            self.assertEqual((status, result["outcome"]), (409, "VERIFICATION_REQUIRED"))
            self.assertEqual(self.order(), self.existing)
        self.assertEqual(self.history()["total"], 4)
        self.assertTrue(all(r["decision"] for r in self.history()["items"]))

    def test_review_and_decision_replay_and_payload_conflict(self):
        review = self.check({**self.facts, "order_id": "ORD-903"}, request_id="review-key")
        replay = self.check({**self.facts, "order_id": "ORD-903"}, request_id="review-key")
        self.assertEqual(replay["review_id"], review["review_id"])
        self.assertTrue(replay["replayed"])
        with self.assertRaises(intake.OrderIntakeError):
            self.check(request_id="review-key")
        body = self.body(review, request_id="decision-key")
        first, _ = intake.decide(review["review_id"], body, actor="alice", db_path=self.path)
        replay, _ = intake.decide(review["review_id"], body, actor="alice", db_path=self.path)
        self.assertEqual({**first, "replayed": True}, replay)
        with self.assertRaises(intake.OrderIntakeError):
            intake.decide(review["review_id"], {**body, "reason": "Changed"}, actor="alice", db_path=self.path)
        with self.assertRaises(intake.OrderIntakeError):
            self.decide(review, "reject")
        self.assertEqual(self.history()["total"], 1)
        self.assertEqual(self.order("ORD-903")["version"], 0)

    def test_review_owner_is_enforced_and_history_is_shared(self):
        review = self.check({**self.facts, "pieces": 151})
        for call in (lambda: intake.get_review(review["review_id"], actor="bob", db_path=self.path),
                     lambda: self.decide(review, actor="bob")):
            with self.assertRaises(intake.OrderIntakeError) as caught:
                call()
            self.assertEqual(caught.exception.status, 404)
        self.assertEqual(intake.history(actor="bob", db_path=self.path)["total"], 1)

    def test_service_revalidates_inputs_independent_of_http(self):
        for changes in ({"pieces": 0}, {"pieces": True}, {"pieces": "20"}, {"category": "INVALID"},
                        {"customer": "  "}, {"order_id": "guess"}, {"order_date": "2026-02-30"},
                        {"order_date": "2026-12-31", "due_date": "2026-01-01"}, {"state": "WORKING"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.check({**self.facts, **changes})
        self.assertEqual(self.history()["total"], 0)
        with self.assertRaises(intake.OrderIntakeError):
            self.check(actor="")

    def test_changed_order_rejects_approval_but_allows_rejection(self):
        stale = self.check({**self.facts, "pieces": 160})
        other = self.check({**self.facts, "pieces": 170})
        rejected = self.check({**self.facts, "pieces": 190})
        self.decide(other)
        response, status = self.decide(stale)
        self.assertEqual((status, response["outcome"]), (409, "ORDER_CHANGED"))
        response, status = self.decide(rejected, "reject")
        self.assertEqual((status, response["outcome"]), (200, "REJECTED"))
        self.assertEqual(self.order()["pieces"], 170)

    def test_snapshot_detects_changes_even_without_version_bump(self):
        review = self.check({**self.facts, "pieces": 160})
        with Database(self.path) as db:
            db.connection.execute("UPDATE orders SET customer='Changed outside the service' WHERE order_id='ORD-045'")
        self.assertEqual(self.decide(review)[0]["outcome"], "ORDER_CHANGED")

    def test_two_missing_reviews_cannot_create_twice(self):
        facts = {**self.facts, "order_id": "ORD-904"}
        first, second = self.check(facts), self.check(facts)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.decide, (first, second)))
        self.assertEqual(sorted(r[0]["outcome"] for r in results), ["CREATED", "ORDER_CHANGED"])
        self.assertEqual(self.order("ORD-904")["version"], 0)

    def test_concurrent_approvals_and_identical_retries_are_serialized(self):
        first = self.check({**self.facts, "pieces": 160})
        second = self.check({**self.facts, "pieces": 170})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.decide, (first, second)))
        self.assertEqual(sorted(r[0]["outcome"] for r in results), ["ORDER_CHANGED", "UPDATED"])
        self.assertEqual(self.order()["version"], 1)
        review = self.check({**self.facts, "order_id": "ORD-905"})
        body = self.body(review)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: intake.decide(review["review_id"], body, actor="alice", db_path=self.path), range(2)))
        self.assertEqual(sorted(r[0]["replayed"] for r in results), [False, True])

    def test_production_and_completed_orders_cannot_be_overwritten(self):
        seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=self.path)
        before = self.order()
        review = self.check({**self.facts, "pieces": 160})
        self.assertFalse(review["can_update"])
        self.assertEqual(self.decide(review)[0]["outcome"], "ORDER_UPDATE_BLOCKED")
        self.assertEqual(self.order(), before)
        with Database(self.path) as db:
            completed = dict(db.connection.execute("SELECT * FROM orders WHERE state='COMPLETED' LIMIT 1").fetchone())
        facts = {field: completed[field] for field in ORDER_FIELDS}
        review = self.check({**facts, "customer": "Changed"})
        self.assertEqual(self.decide(review)[0]["outcome"], "ORDER_UPDATE_BLOCKED")
        self.assertEqual(self.order(completed["order_id"]), completed)

    def test_partial_completion_on_ready_order_is_protected(self):
        with Database(self.path) as db:
            db.connection.execute("UPDATE orders SET completed_pieces=1 WHERE order_id='ORD-045'")
        review = self.check({**self.facts, "pieces": 160})
        self.assertEqual(self.decide(review)[0]["outcome"], "ORDER_UPDATE_BLOCKED")

    def test_order_write_rolls_back_if_audit_cannot_be_saved(self):
        review = self.check({**self.facts, "pieces": 160})
        with patch.object(intake.repo, "save_decision", side_effect=sqlite3.OperationalError("audit unavailable")):
            with self.assertRaises(sqlite3.OperationalError):
                self.decide(review)
        self.assertEqual(self.order(), self.existing)
        self.assertIsNone(intake.get_review(review["review_id"], actor="alice", db_path=self.path)["decision"])

    def test_old_allocation_preview_requires_new_review_after_correction(self):
        preview = chat.create(owner="alice", request_id="preview", db_path=self.path, as_of=date(2026, 4, 1),
                              mode="offline", message="Allocate ORD-045.")
        self.decide(self.check({**self.facts, "pieces": 160}))
        response = chat.turn(preview["session_id"], owner="alice", request_id="confirm-old",
            expected_version=preview["session_version"], db_path=self.path, action="confirm",
            recommendation_id=preview["session"]["recommendation"]["recommendation_id"])
        self.assertFalse(response["committed"])
        self.assertEqual(self.order()["state"], "READY")

    def test_audit_pagination_and_restart_recovery(self):
        for i in range(3):
            self.check(request_id=f"pending-{i}")
        first = self.history(limit=2)
        second = self.history(limit=2, offset=2)
        self.assertEqual(first["total"], 3)
        self.assertEqual(len({r["review_id"] for r in first["items"] + second["items"]}), 3)
        self.assertEqual(intake.get_review(first["items"][0]["review_id"], actor="alice", db_path=self.path), first["items"][0])


class RegistrationHTTPTests(unittest.TestCase):
    body = RegistrationTests.body

    def setUp(self):
        RegistrationTests.setUp(self)
        set_password(self.path, "alice", "Disposable-password-for-intake-tests")
        set_password(self.path, "bob", "Disposable-password-for-intake-tests")
        self.client = self.enterContext(TestClient(create_app(Settings(db_path=self.path, require_auth=True))))

    def test_http_auth_validation_owner_and_audit(self):
        body = {"request_id": "http-check", "order": {**self.facts, "order_id": "ORD-906"}}
        self.assertEqual(self.client.post("/api/order-intake/reviews", json=body).status_code, 401)
        self.assertEqual(self.client.get("/api/order-intake/history").status_code, 401)
        self.client.post("/api/auth/login", json={"username": "alice", "password": "Disposable-password-for-intake-tests"})
        self.assertEqual(self.client.post("/api/order-intake/reviews", json={**body, "actor": "bob"}).status_code, 400)
        review = self.client.post("/api/order-intake/reviews", json=body).json()
        decision = self.body(review)
        self.assertEqual(self.client.post(f"/api/order-intake/reviews/{review['review_id']}/decision", json=decision).status_code, 200)
        self.assertEqual(self.client.get("/api/orders/ORD-906").status_code, 200)
        self.assertEqual(self.client.get("/api/order-intake/history").json()["items"][0]["decision"]["actor"], "alice")
        self.client.post("/api/auth/logout", json={})
        self.client.post("/api/auth/login", json={"username": "bob", "password": "Disposable-password-for-intake-tests"})
        self.assertEqual(self.client.get(f"/api/order-intake/reviews/{review['review_id']}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/order-intake/reviews/{review['review_id']}/decision", json=decision).status_code, 404)
        self.assertEqual(self.client.get("/api/order-intake/history").status_code, 200)


class RegistrationMigrationTests(unittest.TestCase):
    def test_v9_upgrade_is_additive_repeatable_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            for fail in (False, True):
                path = str(Path(directory) / f"v9-{fail}.sqlite3")
                with patch.object(Database, "_upgrade_order_intake"), patch.object(Database, "_upgrade_chat_registration"):
                    with Database(path) as db:
                        before = [tuple(r) for r in db.connection.execute("SELECT * FROM orders")]
                        if fail:
                            db.connection.execute("CREATE TRIGGER fail_v10 BEFORE INSERT ON schema_migrations WHEN NEW.version=10 BEGIN SELECT RAISE(ABORT,'migration test'); END")
                if fail:
                    with self.assertRaises(sqlite3.Error):
                        Database(path)
                    with closing(sqlite3.connect(path)) as connection:
                        self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 9)
                        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='order_intake_reviews'").fetchone())
                        self.assertEqual([tuple(r) for r in connection.execute("SELECT * FROM orders")], before)
                else:
                    for _ in range(2):
                        with Database(path) as db:
                            self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], DB_VERSION)
                            self.assertEqual([tuple(r) for r in db.connection.execute("SELECT * FROM orders")], before)
                            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM order_intake_reviews").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
