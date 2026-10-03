import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SessionCLI(unittest.TestCase):
    def test_persistent_cli_roundtrip_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "cli.sqlite3")
            def call(*args):
                r = subprocess.run([sys.executable, "-m", "app.session_cli", "--db", path, *args], capture_output=True, text=True)
                return r.returncode, json.loads(r.stdout)
            self.assertEqual(call("create", "--session-id", "cli")[0], 0)
            code, result = call("turn", "cli", "--expected-version", "0", "--request-id", "draft", "--message", "Allocate ORD-045.")
            self.assertEqual(code, 0)
            self.assertEqual(result["result"]["decision_status"], "REVIEW")
            args = ("turn", "cli", "--expected-version", "1", "--request-id", "confirm", "--action", "confirm")
            self.assertTrue(call(*args)[1]["committed"])
            self.assertTrue(call(*args)[1]["replayed"])
            self.assertEqual(call("inspect", "cli")[1]["state"], "CLOSED")
            self.assertEqual(call("turn", "cli", "--expected-version", "1", "--request-id", "late", "--message", "fastest")[0], 1)
