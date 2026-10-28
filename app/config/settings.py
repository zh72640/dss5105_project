"""Local application configuration. CLI arguments take precedence over environment."""
import os
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: str = str(ROOT / "runtime/dispatch.sqlite3")
    backend: str = "offline"
    as_of: date | None = None
    require_auth: bool = True
    max_body_bytes: int = 50_000

    @classmethod
    def from_env(cls):
        business_date = os.getenv("DISPATCH_AS_OF", "")
        # AGENT_MODE is canonical; PARSER_BACKEND=offline remains a legacy alias.
        mode = os.getenv("AGENT_MODE") or (
            "offline" if os.getenv("PARSER_BACKEND", "").strip() == "offline" else None)
        if mode not in (None, "offline", "llm"):
            mode = "offline"
        backend = mode or "offline"
        return cls(db_path=os.getenv("DISPATCH_DB", cls.db_path), backend=backend,
                   as_of=date.fromisoformat(business_date) if business_date else None,
                   require_auth=os.getenv("DISPATCH_NO_AUTH", "0") != "1")

    def resolve(self):
        from app.db.database import Database
        if self.db_path == ":memory:":
            raise ValueError("HTTP requires a file SQLite database shared by request threads.")
        if self.backend not in ("offline", "llm"):
            raise ValueError("Unknown mode; use offline or llm.")
        with Database(self.db_path) as db:
            latest = db.connection.execute("SELECT MAX(as_of_date) FROM workshop_queue").fetchone()[0]
        business_date = self.as_of or (date.fromisoformat(latest) if latest else date(2026, 4, 1))
        if latest and business_date < date.fromisoformat(latest):
            raise ValueError("Business date cannot precede the latest workshop queue snapshot.")
        return replace(self, db_path=str(Path(self.db_path).resolve()), as_of=business_date)
