"""The request queue exposes presentation facts without crossing account scope."""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.services.chat import service as chat


class RequestQueueReadModel(unittest.TestCase):
    def test_request_facts_keep_owner_scope_and_pagination(self):
        with tempfile.TemporaryDirectory() as folder:
            database = str(Path(folder) / "queue.sqlite3")
            for owner, key, message in (
                ("alice", "first", "Allocate ORD-045 cheapest."),
                ("bob", "private", "Allocate ORD-041 cheapest."),
                ("alice", "second", ""),
            ):
                chat.create(owner=owner, request_id=key, db_path=database,
                            as_of=date(2026, 4, 1), mode="offline", message=message)
            first = chat.list_sessions(owner="alice", db_path=database, limit=1)
            older = chat.list_sessions(owner="alice", db_path=database,
                                       limit=1, after=first["next_cursor"])
            self.assertEqual(first["items"][0]["task_state"], "COLLECTING")
            row = older["items"][0]
            self.assertEqual(row["order_id"], "ORD-045")
            self.assertEqual(row["task_state"], "RECOMMENDED")
            self.assertTrue(row["created_at"])
            self.assertLess(row["cursor"], first["items"][0]["cursor"])
            self.assertIsNone(older["next_cursor"])
