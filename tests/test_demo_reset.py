from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.cli.reset_demo import reset_demo
from app.core.security import password_hash
from app.db.database import Database
from app.services.chat import service as chat


class DemoReset(unittest.TestCase):
    def test_requires_explicit_stop_and_preserves_accounts_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'demo.sqlite3'
            encoded = password_hash('test-password-only')
            with Database(path, initial_account=('tester',encoded)):
                pass
            chat.create(owner='tester', request_id='create', db_path=path, as_of=date(2026,4,1))
            with self.assertRaisesRegex(ValueError,'Stop the server'):
                reset_demo(path)
            result = reset_demo(path, server_stopped=True)
            with sqlite3.connect(result['backup']) as backup:
                self.assertEqual(backup.execute('SELECT COUNT(*) FROM chat_sessions').fetchone()[0],1)
            with Database(path) as fresh:
                for table in ('chat_sessions','working_order','login_sessions'):
                    self.assertEqual(fresh.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
                self.assertEqual(fresh.connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0],120)
                self.assertEqual(fresh.connection.execute("SELECT password_hash FROM desk_users WHERE username='tester'").fetchone()[0],encoded)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'missing.sqlite3'
            with self.assertRaises(FileNotFoundError):
                reset_demo(path, server_stopped=True)
            self.assertFalse(path.exists())
