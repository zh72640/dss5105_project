"""Role boundaries, account provisioning and transactional upgrades on disposable databases."""
import hashlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing, redirect_stderr
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.dependencies import Context, require_admin
from app.core import admin_account, security
from app.cli import auth as account_cli
from app.config.settings import Settings
from app.db.database import Database, DB_VERSION
from app.db.import_data import load_seed
from app.main import create_app
from app.services.auth import auth_me
from app.cli.setup import initialize_database

ADMIN_TEST_PASSWORD = "Disposable-admin-test-password"
USER_TEST_PASSWORD = "Disposable-user-test-password"


class AccountRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "accounts.sqlite3"
        self.admin_hash = security.password_hash(ADMIN_TEST_PASSWORD)
        self.enterContext(patch.object(admin_account, "ADMIN_PASSWORD_HASH", self.admin_hash))

    def initialize(self):
        initialize_database(self.path, load_seed(), "student", USER_TEST_PASSWORD)

    def client(self, *, require_auth=True):
        app = create_app(Settings(db_path=str(self.path), require_auth=require_auth))
        # Exercise the actual dependency without adding a production admin endpoint.
        @app.get("/test/admin-only")
        def admin_only(ctx: Context = Depends(require_admin)):
            return {"username": ctx.username, "role": ctx.role}
        return self.enterContext(TestClient(app))

    def old_database(self, version, username="student"):
        upgrades = {2: "_upgrade_lifecycle", 3: "_upgrade_sessions", 4: "_upgrade_desk",
                    5: "_upgrade_jobs", 6: "_upgrade_job_recovery", 7: "_upgrade_account_roles", 8: "_upgrade_chat",
                    9: "_upgrade_agent"}
        with ExitStack() as patches:
            for target, method in upgrades.items():
                if target > version:
                    patches.enter_context(patch.object(Database, method))
            with Database(self.path) as db:
                if version >= 4:
                    db.connection.execute("INSERT INTO desk_users VALUES (?,?,?)",
                                          (username, security.password_hash(USER_TEST_PASSWORD), "saved-account-time"))
                    db.connection.execute("INSERT INTO login_sessions VALUES (?,?,?)",
                                          (hashlib.sha256(b"existing-cookie").hexdigest(), username, 4102444800))
                return [tuple(r) for r in db.connection.execute(
                    "SELECT order_id,customer,due_date FROM orders ORDER BY order_id")]

    def test_setup_provisions_admin_and_regular_account_once(self):
        self.initialize()
        with Database(self.path) as db:
            rows = [tuple(r) for r in db.connection.execute("SELECT username,role FROM desk_users ORDER BY username")]
            self.assertEqual(rows, [("admin", "admin"), ("student", "user")])
            admin_before = tuple(db.connection.execute("SELECT * FROM desk_users WHERE username='admin'").fetchone())
            self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], DB_VERSION)
        with Database(self.path) as db:
            self.assertEqual(tuple(db.connection.execute("SELECT * FROM desk_users WHERE username='admin'").fetchone()), admin_before)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM desk_users").fetchone()[0], 2)

    def test_reserved_initial_names_leave_no_database(self):
        for username in ("admin", "Admin", "ADMIN", "aDmIn"):
            with self.subTest(username=username), self.assertRaisesRegex(ValueError, "reserved"):
                initialize_database(self.path, load_seed(), username, USER_TEST_PASSWORD)
            self.assertFalse(self.path.exists())

    def test_low_level_initial_account_cannot_claim_admin(self):
        with self.assertRaisesRegex(ValueError, "reserved"):
            Database(self.path, initial_account=("ADMIN", self.admin_hash))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0)

    def test_registration_and_reset_cannot_replace_admin(self):
        self.initialize()
        token = security.login(self.path, "admin", ADMIN_TEST_PASSWORD)
        for function in (security.create_account, security.reset_password, security.set_password):
            for username in ("admin", "Admin", "ADMIN"):
                with self.subTest(function=function.__name__, username=username), self.assertRaisesRegex(ValueError, "reserved"):
                    function(self.path, username, USER_TEST_PASSWORD)
        self.assertEqual(security.identify_principal(self.path, token), {"username": "admin", "role": "admin"})
        self.assertIsNone(security.login(self.path, "admin", USER_TEST_PASSWORD))
        security.create_account(self.path, "second", USER_TEST_PASSWORD)
        second = security.login(self.path, "second", USER_TEST_PASSWORD)
        self.assertEqual(security.identify_principal(self.path, second)["role"], "user")

    def test_reset_guard_checks_role_as_well_as_reserved_name(self):
        self.initialize()
        with Database(self.path) as db:
            db.connection.execute("UPDATE desk_users SET role='admin' WHERE username='student'")
        for function in (security.set_password, security.reset_password):
            with self.assertRaisesRegex(ValueError, "Administrator accounts"):
                function(self.path, "student", USER_TEST_PASSWORD + "new")
        self.assertIsNotNone(security.login(self.path, "student", USER_TEST_PASSWORD))

    def test_admin_login_role_cookie_and_authorization(self):
        self.initialize()
        client = self.client()
        anonymous = client.get("/api/auth/me").json()
        self.assertIsNone(anonymous["role"])
        self.assertFalse(anonymous["setup_required"])
        self.assertEqual(client.get("/test/admin-only").status_code, 401)
        wrong = client.post("/api/auth/login", json={"username": "admin", "password": "incorrect-password"})
        self.assertEqual(wrong.status_code, 401)
        self.assertNotIn("password", wrong.text)
        login = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_TEST_PASSWORD})
        self.assertEqual(login.json(), {"username": "admin", "role": "admin"})
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertIn("SameSite=Strict", login.headers["set-cookie"])
        self.assertEqual(client.get("/api/auth/me").json()["role"], "admin")
        self.assertEqual(client.get("/test/admin-only").status_code, 200)
        self.assertEqual(client.get("/api/dashboard").status_code, 200)
        restarted = self.client()
        restarted.cookies.update(client.cookies)
        self.assertEqual(restarted.get("/api/auth/me").json()["role"], "admin")
        self.assertEqual(client.post("/api/auth/logout", json={}).status_code, 200)
        self.assertIsNone(client.get("/api/auth/me").json()["role"])
        self.assertEqual(restarted.get("/test/admin-only").status_code, 401)

    def test_regular_user_cannot_spoof_admin_role(self):
        self.initialize()
        client = self.client()
        payload = {"username": "student", "password": USER_TEST_PASSWORD}
        self.assertEqual(client.post("/api/auth/login", json={**payload, "role": "admin"}).status_code, 400)
        self.assertEqual(client.post("/api/auth/login", json=payload).json()["role"], "user")
        self.assertEqual(client.get("/test/admin-only", headers={"X-Role": "admin"}).status_code, 403)
        self.assertEqual(client.get("/api/auth/me").json()["role"], "user")
        self.assertEqual(client.get("/api/dashboard").status_code, 200)

    def test_current_database_role_is_used_for_existing_cookie(self):
        self.initialize()
        client = self.client()
        client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_TEST_PASSWORD})
        with Database(self.path) as db:
            db.connection.execute("UPDATE desk_users SET role='user' WHERE username='admin'")
        self.assertEqual(client.get("/test/admin-only").status_code, 403)
        self.assertEqual(client.get("/api/auth/me").json()["role"], "user")

    def test_demo_mode_is_regular_and_cannot_use_admin_dependency(self):
        self.initialize()
        client = self.client(require_auth=False)
        self.assertEqual(client.get("/api/auth/me").json(), {
            "username": "local-demo", "role": "user", "auth_required": False, "setup_required": False})
        self.assertEqual(client.get("/test/admin-only").status_code, 403)

    def test_built_in_admin_does_not_hide_missing_regular_account(self):
        with Database(self.path):
            pass
        self.assertTrue(auth_me(self.path, None, require_auth=True)["setup_required"])
        self.assertEqual(auth_me(self.path, "admin", require_auth=True)["role"], "admin")

    def test_versions_one_through_six_preserve_orders_and_accounts(self):
        for version in range(1, 7):
            with self.subTest(version=version):
                self.path = Path(self.temp.name) / f"version-{version}.sqlite3"
                orders = self.old_database(version)
                with Database(self.path) as db:
                    self.assertEqual([tuple(r) for r in db.connection.execute(
                        "SELECT order_id,customer,due_date FROM orders ORDER BY order_id")], orders)
                    self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], DB_VERSION)
                    self.assertEqual(db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                if version >= 4:
                    self.assertIsNotNone(security.login(self.path, "student", USER_TEST_PASSWORD))
                    self.assertEqual(security.identify_principal(self.path, "existing-cookie"), {"username": "student", "role": "user"})
                self.assertIsNotNone(security.login(self.path, "admin", ADMIN_TEST_PASSWORD))

    def test_existing_admin_name_causes_transactional_rollback(self):
        for index, username in enumerate(("admin", "Admin", "ADMIN")):
            with self.subTest(username=username):
                self.path = Path(self.temp.name) / f"collision-{index}.sqlite3"
                self.old_database(6, username)
                with closing(sqlite3.connect(self.path)) as db, db:
                    before = db.execute("SELECT * FROM desk_users").fetchall()
                with self.assertRaisesRegex(ValueError, "username conflict"):
                    Database(self.path)
                with closing(sqlite3.connect(self.path)) as db, db:
                    self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 6)
                    self.assertNotIn("role", [r[1] for r in db.execute("PRAGMA table_info(desk_users)")])
                    self.assertEqual(db.execute("SELECT * FROM desk_users").fetchall(), before)

    def test_cli_rejects_admin_creation_and_password_reset(self):
        self.initialize()
        for flags in ([], ["--reset-password"]):
            with patch("sys.argv", ["app.cli.auth", "admin", "--db", str(self.path), *flags]), \
                    patch.object(account_cli, "prompt_password", return_value=USER_TEST_PASSWORD), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                account_cli.main()
            self.assertEqual(error.exception.code, 2)
        self.assertIsNotNone(security.login(self.path, "admin", ADMIN_TEST_PASSWORD))

    def test_concurrent_upgrade_provisions_one_administrator(self):
        self.old_database(6)
        def open_database(_):
            with Database(self.path) as db:
                return db.connection.execute("SELECT COUNT(*) FROM desk_users WHERE role='admin'").fetchone()[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(open_database, range(2))), [1, 1])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=7").fetchone()[0], 1)

    def test_failed_version_record_rolls_back_role_and_admin_insert(self):
        self.old_database(6)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TRIGGER fail_roles BEFORE INSERT ON schema_migrations
                WHEN NEW.version=7 BEGIN SELECT RAISE(ABORT,'simulated failure'); END""")
        with self.assertRaises(sqlite3.DatabaseError):
            Database(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertNotIn("role", [r[1] for r in db.execute("PRAGMA table_info(desk_users)")])
            self.assertEqual(db.execute("SELECT username FROM desk_users").fetchall(), [("student",)])
            self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
