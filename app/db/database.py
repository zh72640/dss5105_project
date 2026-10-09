import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.db.import_data import load_seed

ROOT = Path(__file__).resolve().parents[2]
DB_VERSION = 4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path=":memory:", *, seed_data=None, initial_account=None):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        try:
            self.initialize(seed_data=seed_data, initial_account=initial_account)
        except Exception:
            self.close()
            raise

    def initialize(self, *, seed_data=None, initial_account=None):
        # DDL and CSV import are one migration transaction, safe for concurrent opens.
        with self.transaction():
            has_table = self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
            if has_table:
                if seed_data is not None or initial_account is not None:
                    raise ValueError("Database is already initialized; existing data was not changed.")
                version = self.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                if version not in (1, 2, 3, DB_VERSION):
                    raise sqlite3.DatabaseError("unsupported_database_version")
                if version == 1:
                    self._upgrade_lifecycle()
                if version < 3:
                    self._upgrade_sessions()
                if version < 4:
                    self._upgrade_desk()
                return
            seed_data = seed_data or load_seed()
            sql = (Path(__file__).parent / "migrations/001_initial.sql").read_text()
            for statement in sql.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
            for row in seed_data.orders:
                state = "COMPLETED" if row["status"] == "COMPLETE" else "READY"
                self.connection.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", (
                    row["order_id"], row["customer"], row["product"], row["category"], row["pieces"],
                    row["order_date"], row["due_date"], row["status"], state))
                if state == "COMPLETED":
                    self.connection.execute("INSERT INTO completed_order VALUES (?,?)", (row["order_id"], row["completed_date"] or None))
            for r in seed_data.workshops:
                self.connection.execute("INSERT INTO workshops VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    r["workshop_id"], r["name"], r["capacity_pieces_per_day"], r["pickup_lead_days"],
                    r["defect_rate"], r["cost_per_piece"], r["makes"], r["status"],
                    r["max_batch_pieces"], r["notes"]))
                self.connection.execute("INSERT INTO workshop_queue VALUES (?,?,?)", (r["workshop_id"], r["current_queue_days"], seed_data.as_of.isoformat()))
            self.connection.execute("INSERT INTO schema_migrations VALUES (?,?)", (1, utc_now()))
            self._upgrade_lifecycle()
            self._upgrade_sessions()
            self._upgrade_desk()
            if initial_account is not None:
                username, encoded_password = initial_account
                self.connection.execute("INSERT INTO desk_users VALUES (?,?,?)", (username, encoded_password, utc_now()))

    def _upgrade_desk(self):
        sql = (Path(__file__).parent / "migrations/004_desk.sql").read_text()
        for statement in sql.split(";"):
            if statement.strip():
                self.connection.execute(statement)
        self.connection.execute("INSERT INTO schema_migrations VALUES (?,?)", (4, utc_now()))

    def _upgrade_sessions(self):
        sql = (Path(__file__).parent / "migrations/003_sessions.sql").read_text()
        for statement in sql.split(";"):
            if statement.strip():
                self.connection.execute(statement)
        self.connection.execute("INSERT INTO schema_migrations VALUES (?,?)", (3, utc_now()))

    def _upgrade_lifecycle(self):
        sql = (Path(__file__).parent / "migrations/002_lifecycle.sql").read_text()
        for statement in sql.split(";"):
            if statement.strip():
                self.connection.execute(statement)
        # Legacy queues are FIFO: the tail contains the newest assignments.
        # Recover their unelapsed reservations without resetting persisted queues.
        queues = self.connection.execute("SELECT * FROM workshop_queue").fetchall()
        for queue in queues:
            remaining = queue["current_queue_days"]
            rows = self.connection.execute("""SELECT wo.rowid AS position, wo.*, w.capacity_pieces_per_day
                FROM working_order wo JOIN workshops w USING(workshop_id)
                WHERE wo.workshop_id=? ORDER BY wo.rowid DESC""", (queue["workshop_id"],)).fetchall()
            for row in rows:
                capacity = row["capacity_pieces_per_day"]
                reserved = min(remaining, row["pieces"] / capacity)
                self.connection.execute("""UPDATE working_order SET capacity_at_assignment=?,queue_remaining_days=?
                    WHERE rowid=?""", (capacity, reserved, row["position"]))
                remaining = max(0., remaining - reserved)
            self.connection.execute("UPDATE workshop_queue SET baseline_queue_days=? WHERE workshop_id=?",
                                    (remaining, queue["workshop_id"]))
        self.connection.execute("INSERT INTO schema_migrations VALUES (?,?)", (2, utc_now()))

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
