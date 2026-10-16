"""Exercise real CLI processes against one durable database."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LifecycleCLITests(unittest.TestCase):
    def test_inspect_complete_and_stale_event_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'cli.sqlite3')
            allocation = subprocess.run([sys.executable, '-m', 'app.cli', '--message', 'Allocate ORD-045 to Nimble Needle.',
                                         '--backend', 'offline', '--db', path], capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(allocation.stdout)['result']['success'])
            def command(*arguments):
                return subprocess.run([sys.executable, '-m', 'app.lifecycle_cli', *arguments, '--db', path],
                                      capture_output=True, text=True)
            current = command('inspect', 'ORD-045')
            self.assertEqual(json.loads(current.stdout)['version'], 1)
            args = ('complete', 'ORD-045', '--actor', 'cli-operator', '--reason', 'Confirmed production',
                    '--expected-version', '1', '--workshop-id', 'W6', '--pieces', '150')
            result = command(*args, '--event-id', 'cli-complete')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['order']['state'], 'COMPLETED')
            replay = command(*args, '--event-id', 'cli-complete')
            self.assertEqual(replay.returncode, 0)
            self.assertTrue(json.loads(replay.stdout)['replayed'])
            conflict = command(*args, '--event-id', 'cli-stale')
            self.assertEqual(conflict.returncode, 1)
            self.assertEqual(json.loads(conflict.stdout)['result']['reason_codes'], ['VERSION_CONFLICT'])
            self.assertEqual(command('cancel', 'ORD-045').returncode, 2)
            missing = command('inspect', 'ORD-999')
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(json.loads(missing.stdout)['error'], 'ORDER_NOT_FOUND')
