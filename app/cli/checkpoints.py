"""Remove old diagnostic graph attempts without changing business history."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from langgraph.checkpoint.sqlite import SqliteSaver
from app.config.settings import Settings
from app.core.security import require_initialized


def prune_checkpoints(db_path, retention_days=30):
    if type(retention_days) is not int or retention_days < 1:
        raise ValueError("retention_days must be a positive integer")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with closing(sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)) as connection:
        if connection.execute("SELECT name FROM sqlite_master WHERE name='checkpoints'").fetchone() is None:
            return 0
        saver = SqliteSaver(connection)
        newest = {}
        for entry in saver.list(None):
            thread = entry.config["configurable"]["thread_id"]
            stamp = datetime.fromisoformat(entry.checkpoint["ts"])
            newest[thread] = max(stamp, newest.get(thread, stamp))
        expired = [thread for thread, stamp in newest.items() if stamp < cutoff]
        for thread in expired:
            saver.delete_thread(thread)
        return len(expired)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=Settings.db_path)
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    require_initialized(args.db)
    print(f"Removed {prune_checkpoints(args.db, args.retention_days)} old workflow attempts.")


if __name__ == "__main__":
    main()
