"""The workflow must expose failures and preserve previous evidence."""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluation.run_test_workflow import execute_stage, inspect_result, main


class TestWorkflow(unittest.TestCase):
    def test_failed_process_never_becomes_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = execute_stage('python', [sys.executable, '-c', 'raise SystemExit(7)'],
                                   Path(directory), timeout=10, env=os.environ.copy())
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['returncode'], 7)

    def test_timeout_is_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('evaluation.run_test_workflow.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(['test'], 1)):
            result = execute_stage('python', ['test'], Path(directory), timeout=1, env={})
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('exceeded', result['error'])

    def test_zero_discovered_tests_cannot_pass(self):
        for stage, log in [('python', 'Ran 0 tests in 0.000s\nOK'), ('frontend', '# tests 0\n')]:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                inspect_result(stage, Path('.'), log)

    def language_evidence(self, output, changed_id):
        directory = output / 'language'
        directory.mkdir()
        cases = [{'id': f'R{n:02}', 'expected_behavior': 'DECLINE' if n == changed_id else 'ALLOCATE',
                  'actual_behavior': 'CLARIFY' if n == changed_id else 'ALLOCATE',
                  'behavior_match': n != changed_id} for n in range(1, 31)]
        (directory / 'cases.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in cases))
        (directory / 'summary.json').write_text(json.dumps({'cases': 30, 'service_successes': 30,
            'mode': 'offline', 'production_rows_written': 0, 'behavior_matches': 29}))

    def test_known_label_difference_remains_a_visible_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            self.language_evidence(Path(directory), 2)
            details, warnings = inspect_result('language', Path(directory), '')
        self.assertEqual(details['differences'][0]['id'], 'R02')
        self.assertTrue(warnings)

    def test_new_language_mismatch_fails_instead_of_becoming_a_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            self.language_evidence(Path(directory), 1)
            with self.assertRaisesRegex(ValueError, 'Unexpected language regressions'):
                inspect_result('language', Path(directory), '')

    def test_existing_evidence_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            evidence = Path(directory) / 'summary.json'
            evidence.write_text('previous evidence')
            with self.assertRaises(SystemExit) as rejected:
                main(['--output-dir', directory])
            self.assertEqual(rejected.exception.code, 2)
            self.assertEqual(evidence.read_text(), 'previous evidence')
