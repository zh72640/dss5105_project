"""First-run import and account tests; CSV fixtures exist only in temporary dirs."""
import csv
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import date
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app import auth
from app.db.database import Database
from app.db.import_data import ORDER_FIELDS, WORKSHOP_FIELDS, load_seed
from app.server import make_server
from app.setup import initialize_database, main

PASSWORD = "Personal-data-test-password"
AS_OF = date(2026, 10, 9)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dispatch setup ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "personal.sqlite3"
        self.orders = self.root / "my orders.csv"
        self.workshops = self.root / "my workshops.csv"
        self.order = dict(zip(ORDER_FIELDS, ("ORD-901", "Private Customer", "Custom knit", "TOPS", "60",
                                             "2026-10-01", "2026-10-20", "READY")))
        self.workshop = dict(zip(WORKSHOP_FIELDS, ("W9", "Private Workshop", "30", "1", "0.02", "2.5",
                                                  "TOPS", "ACTIVE", "2")))
        self.write_files()

    def write_files(self, orders=None, workshops=None):
        for path, fields, rows in ((self.orders, ORDER_FIELDS, orders if orders is not None else [self.order]),
                                   (self.workshops, WORKSHOP_FIELDS, workshops if workshops is not None else [self.workshop])):
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

    def seed(self):
        return load_seed(self.orders, self.workshops, AS_OF)

    def initialize(self):
        return initialize_database(self.db, self.seed(), "professor", PASSWORD)

    def test_import_snapshot_and_existing_file_protection(self):
        self.initialize()
        self.orders.unlink()
        self.workshops.unlink()
        with Database(self.db) as db:
            self.assertEqual(db.connection.execute("SELECT order_id FROM orders").fetchall()[0][0], "ORD-901")
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)
            self.assertEqual(db.connection.execute("SELECT as_of_date FROM workshop_queue").fetchone()[0], AS_OF.isoformat())
            self.assertEqual(db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            initialize_database(self.db, load_seed(), "professor", PASSWORD)
        self.assertEqual(self.db.read_bytes(), before)
        empty = self.root / "existing-empty.sqlite3"
        empty.touch()
        with self.assertRaisesRegex(ValueError, "already exists"):
            initialize_database(empty, load_seed(), "professor", PASSWORD)
        self.assertEqual(empty.stat().st_size, 0)

    def test_invalid_csv_has_file_and_row_and_creates_no_database(self):
        for key, value, order in (("pieces", "0", True), ("due_date", "2026-02-30", True),
                                 ("order_id", "arbitrary-id", True), ("category", "SHOES", True),
                                 ("capacity_pieces_per_day", "0", False), ("cost_per_piece", "NaN", False),
                                 ("defect_rate", "1.2", False), ("current_queue_days", "-1", False)):
            with self.subTest(key=key):
                self.write_files(orders=[{**self.order, key: value}] if order else None,
                                 workshops=[{**self.workshop, key: value}] if not order else None)
                with self.assertRaisesRegex(ValueError, "row 2"):
                    self.seed()
                self.assertFalse(self.db.exists())

    def test_missing_columns_duplicates_and_workshop_limit(self):
        self.orders.write_text("order_id\nORD-901\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing columns"):
            self.seed()
        self.write_files(orders=[self.order, self.order])
        with self.assertRaisesRegex(ValueError, "row 3: duplicate"):
            self.seed()
        self.write_files(workshops=[{**self.workshop, "workshop_id": f"W{i}", "name": f"Shop {i}"} for i in range(1, 10)])
        with self.assertRaisesRegex(ValueError, "at most 8"):
            self.seed()

    def test_invalid_account_or_transaction_failure_leaves_no_database(self):
        with self.assertRaises(ValueError):
            initialize_database(self.db, self.seed(), "professor", "short")
        self.assertFalse(self.db.exists())
        with patch.object(Database, "_upgrade_desk", side_effect=sqlite3.OperationalError("simulated failure")):
            with self.assertRaises(sqlite3.Error):
                self.initialize()
        self.assertFalse(self.db.exists())

    def test_duplicate_preserves_password_and_login_then_explicit_reset(self):
        self.initialize()
        token = auth.login(self.db, "professor", PASSWORD)
        with self.assertRaisesRegex(ValueError, "already exists"):
            auth.create_account(self.db, "professor", PASSWORD + "-new")
        self.assertEqual(auth.identify(self.db, token), "professor")
        self.assertIsNotNone(auth.login(self.db, "professor", PASSWORD))
        self.assertIsNone(auth.login(self.db, "professor", PASSWORD + "-new"))
        auth.reset_password(self.db, "professor", PASSWORD + "-new")
        self.assertIsNone(auth.identify(self.db, token))
        self.assertIsNone(auth.login(self.db, "professor", PASSWORD))
        self.assertIsNotNone(auth.login(self.db, "professor", PASSWORD + "-new"))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            auth.reset_password(self.db, "unknown", PASSWORD)
        auth.create_account(self.db, "second", PASSWORD)
        self.assertIsNotNone(auth.login(self.db, "second", PASSWORD))

    def test_setup_wizard_and_cancel(self):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["1", "", "n"]), redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.db)]), 0)
        self.assertFalse(self.db.exists())
        with patch("app.setup.prompt_password", return_value=PASSWORD), redirect_stdout(output):
            self.assertEqual(main(["--orders", str(self.orders), "--workshops", str(self.workshops),
                                   "--as-of", AS_OF.isoformat(), "--db", str(self.db),
                                   "--username", "professor", "--yes"]), 0)
        self.assertIn("Account created successfully.", output.getvalue())
        self.assertIsNotNone(auth.login(self.db, "professor", PASSWORD))

    def test_sample_setup_and_account_cli_messages(self):
        with patch("app.setup.prompt_password", return_value=PASSWORD), redirect_stdout(io.StringIO()):
            main(["--sample", "--as-of", "2026-04-01", "--db", str(self.db), "--username", "professor", "--yes"])
        with Database(self.db) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 120)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM workshops").fetchone()[0], 8)
        for flags, expected in (([], "Account created successfully."), (["--reset-password"], "Password reset successfully.")):
            output = io.StringIO()
            with patch("sys.argv", ["app.auth", "newuser", "--db", str(self.db), *flags]), \
                    patch("app.auth.prompt_password", return_value=PASSWORD), redirect_stdout(output):
                auth.main()
            self.assertIn(expected, output.getvalue())

    def test_missing_database_preflight_does_not_create_sample(self):
        with self.assertRaisesRegex(ValueError, "app.setup"):
            auth.require_initialized(self.db)
        self.assertFalse(self.db.exists())

    def test_personal_data_login_preview_confirmation_and_restart(self):
        self.initialize()
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            make_server(0, self.db, as_of=date(2026, 4, 1))
        server = make_server(0, self.db, backend="offline")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        base = f"http://127.0.0.1:{server.server_port}"
        def call(path, data=None):
            request = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                              headers={"Content-Type": "application/json"})
            with client.open(request, timeout=5) as response:
                return json.load(response)
        try:
            self.assertEqual(call("/api/health")["as_of_date"], AS_OF.isoformat())
            call("/api/auth/login", {"username": "professor", "password": PASSWORD})
            self.assertEqual(call("/api/workshops")["items"][0]["name"], "Private Workshop")
            session = call("/api/sessions", {"session_id": "private"})["session"]
            result = call("/api/sessions/private/turns", {"request_id": "preview", "expected_version": session["version"],
                          "action": "message", "message": "Allocate ORD-901."})
            self.assertEqual(result["result"]["decision_status"], "REVIEW")
            self.assertEqual(result["result"]["estimated_cost"], 150)
            self.assertEqual(result["result"]["allocation"][0]["workshop_id"], "W9")
            self.assertFalse(result["committed"])
            confirmed = call("/api/sessions/private/turns", {"request_id": "confirm", "expected_version": result["session"]["version"], "action": "confirm"})
            self.assertTrue(confirmed["committed"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        with Database(self.db) as db:
            self.assertEqual(db.connection.execute("SELECT state FROM orders").fetchone()[0], "WORKING")
        restarted = make_server(0, self.db)
        restarted.server_close()
        self.assertIsNotNone(auth.login(self.db, "professor", PASSWORD))


if __name__ == "__main__":
    unittest.main()
