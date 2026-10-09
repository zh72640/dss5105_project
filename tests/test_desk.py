"""Authentication, approval integrity, read models, exports and v3 upgrades."""
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import date
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app import auth, desk
from app.db.database import Database, DB_VERSION
from app.lifecycle import inspect_order, process_event
from app.pipeline import process_request
from app.server import make_server
from app.sessions import create_session, inspect_session, session_turn

PASSWORD = 'A-test-only-password-2026'


class DeskHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'desk.sqlite3'
        auth.set_password(self.path, 'operator', PASSWORD)
        self.server = make_server(0, self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.cookies = CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.cookies))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def call(self, path, body=None, **headers):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json', **headers})
        try:
            response = self.client.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            value = json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
            return response.status, value, response.headers

    def login(self):
        status, _, headers = self.call('/api/auth/login', {'username': 'operator', 'password': PASSWORD})
        self.assertEqual(status, 200)
        return headers

    def turn(self, sid, version, message='', action='message', **extra):
        return self.call(f'/api/sessions/{sid}/turns', {'request_id': f'{sid}-{version}',
                         'expected_version': version, 'message': message, 'action': action, **extra})

    def test_login_gates_read_write_and_export_and_logout_revokes_cookie(self):
        self.assertIsNone(self.call('/api/auth/me')[1]['username'])
        for path in ('/api/ai/status', '/api/dashboard', '/api/workshops', '/api/audit', '/api/audit/export', '/api/orders/ORD-045', '/api/history', '/api/sessions/unknown'):
            self.assertEqual(self.call(path)[0], 401, path)
        self.assertEqual(self.call('/api/sessions', {})[0], 401)
        self.assertEqual(self.call('/api/auth/login', {'username': 'operator', 'password': 'wrong'})[0], 401)
        headers = self.login()
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertNotIn(PASSWORD, headers['Set-Cookie'])
        self.assertEqual(self.call('/api/dashboard')[0], 200)
        token = next(iter(self.cookies)).value
        self.assertEqual(self.call('/api/auth/logout', {})[0], 200)
        self.assertIsNone(auth.identify(self.path, token))
        self.assertEqual(self.call('/api/audit')[0], 401)

    def test_login_origin_rate_limit_and_untrusted_actor(self):
        self.assertEqual(self.call('/api/auth/login', {'username': 'operator', 'password': PASSWORD}, Origin='https://evil.example')[0], 403)
        self.login()
        self.call('/api/sessions', {'session_id': 's'})
        self.assertEqual(self.turn('s', 0, 'ORD-045', actor='forged')[0], 400)
        self.assertEqual(self.call('/api/sessions', {}, Origin='https://evil.example')[0], 403)
        for _ in range(9):
            self.call('/api/auth/login', {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(self.call('/api/auth/login', {'username': 'operator', 'password': 'wrong'})[0], 429)

    def test_assistant_form_http_summary_status_and_recent_approvals(self):
        self.login()
        self.assertEqual(self.call('/api/ai/status')[1], {'backend':'offline','configured':True,'model':'rules_v1'})
        self.call('/api/sessions', {'session_id':'form'})
        preview = self.turn('form', 0, changes={'order_id':'ORD-045','objective':'min_cost'})[1]
        self.assertIn('awaiting your approval', preview['result']['assistant_reply'])
        self.assertFalse(self.call('/api/dashboard')[1]['recent_allocations'])
        approved = self.turn('form', 1, action='confirm')[1]
        self.assertTrue(approved['committed'])
        recent = self.call('/api/dashboard')[1]['recent_allocations']
        self.assertEqual(recent[0]['order_id'], 'ORD-045')
        self.assertIn('Approved and saved', recent[0]['summary'])
        audit = self.call('/api/audit/form-1')[1]
        self.assertEqual(audit['summary'], approved['result']['assistant_reply'])
        self.assertEqual(audit['approved_by'], 'operator')

    def test_intake_clarification_rejection_revision_approval_and_dashboard(self):
        self.login()
        before = self.call('/api/dashboard')[1]
        self.call('/api/sessions', {'session_id': 'review'})
        first = self.turn('review', 0, 'Allocate cheapest.')[1]
        self.assertEqual(first['session']['state'], 'AWAITING_CLARIFICATION')
        self.assertEqual(self.call('/api/dashboard')[1]['stats']['clarification'], 1)
        preview = self.turn('review', 1, 'ORD-045')[1]
        self.assertIn('explanation', preview['result'])
        self.assertEqual(self.call('/api/orders/ORD-045')[1]['state'], 'READY')
        rejected = self.turn('review', 2, 'Reject recommendation')[1]
        self.assertEqual(rejected['session']['blockers'], ['RECOMMENDATION_REJECTED'])
        refused = self.turn('review', 3, action='confirm')[1]
        self.assertFalse(refused['committed'])
        revised = self.turn('review', 4, 'Allocate ORD-045 to Nimble Needle.', 'replace')[1]
        self.assertEqual(revised['result']['recommended_workshop_id'], 'W6')
        approved = self.turn('review', 5, action='confirm')[1]
        self.assertTrue(approved['committed'])
        self.assertTrue(self.turn('review', 5, action='confirm')[1]['replayed'])
        after = self.call('/api/dashboard')[1]
        self.assertEqual(after['stats']['allocated_today'], before['stats']['allocated_today'] + 1)
        self.assertEqual(after['stats']['unallocated_orders'], before['stats']['unallocated_orders'] - 1)
        self.assertEqual(after['stats']['clarification'], 0)
        self.assertIn('ORD-045', [o['order_id'] for w in after['workshops'] for o in w['orders']])
        audit = self.call('/api/audit/review-5')[1]
        self.assertEqual(audit['approved_by'], 'operator')
        self.assertEqual(audit['original_message'], 'Allocate cheapest.')
        self.assertEqual(audit['parsed']['order_id'], 'ORD-045')
        self.assertTrue(audit['approval_timestamp'])
        self.assertEqual(self.call('/api/sessions/review')[1]['last_response']['result']['decision_status'], 'ALLOCATE')

    def test_filters_pagination_and_export_include_more_than_thirty_records(self):
        self.login()
        create_session(session_id='many', db_path=self.path)
        for i in range(33):
            session_turn('many', expected_version=i, request_id=f'many-{i:02}', message='Allocate cheapest.' if i == 0 else 'cheapest', db_path=self.path)
        first = self.call('/api/audit?page_size=10')[1]
        second = self.call('/api/audit?page_size=10&page=2')[1]
        self.assertEqual(first['total'], 33)
        self.assertFalse({r['request_id'] for r in first['items']} & {r['request_id'] for r in second['items']})
        self.assertEqual(self.call('/api/audit?q=not-found')[1]['total'], 0)
        self.assertEqual(self.call('/api/audit?status=ALLOCATE')[1]['total'], 0)
        exported = self.call('/api/audit/export?format=json&q=not-found&page_size=1')[1]
        self.assertEqual(len(exported['items']), 33)
        status, raw, headers = self.call('/api/audit/export?format=csv')
        self.assertEqual(status, 200)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))), 33)
        self.assertIn('attachment', headers['Content-Disposition'])
        for path in ('/api/audit?page=0', '/api/audit?page_size=101', '/api/audit?page=bad', '/api/audit/export?format=html'):
            self.assertEqual(self.call(path)[0], 400)
        self.assertEqual(self.call('/api/audit/missing')[0], 404)

    def test_workshop_filters_and_read_models_do_not_mutate_business_state(self):
        self.login()
        with Database(self.path) as db:
            before = [tuple(r) for r in db.connection.execute('SELECT * FROM workshop_queue')]
        data = self.call('/api/workshops?status=ACTIVE&category=ACCESSORIES')[1]
        self.assertEqual({w['workshop_id'] for w in data['items']}, {'W2', 'W4', 'W6'})
        self.assertEqual(self.call('/api/workshops?q=nimble')[1]['items'][0]['workshop_id'], 'W6')
        self.assertEqual(self.call('/api/workshops?status=SUSPENDED')[1]['items'][0]['workshop_id'], 'W7')
        self.call('/api/dashboard')
        with Database(self.path) as db:
            self.assertEqual(before, [tuple(r) for r in db.connection.execute('SELECT * FROM workshop_queue')])

    def test_authenticated_lifecycle_cannot_spoof_actor(self):
        self.login()
        self.call('/api/requests', {'message': 'Allocate ORD-045 to Nimble Needle.', 'request_id': 'direct'})
        body = {'action': 'complete', 'order_id': 'ORD-045', 'actor': 'forged', 'reason': 'Received batch',
                'expected_version': 1, 'event_id': 'done', 'workshop_id': 'W6', 'pieces': 10}
        result = self.call('/api/events', body)[1]
        self.assertEqual(result['event']['actor'], 'operator')
        self.assertEqual(self.call('/api/audit/direct')[1]['approved_by'], 'operator')
        self.assertEqual(self.call('/api/audit/done')[1]['actor'], 'operator')

    def test_assets_are_served_and_arbitrary_paths_are_not(self):
        for path, mime in (('/', 'text/html'), ('/desk.js', 'text/javascript'), ('/desk.css', 'text/css')):
            code, content, headers = self.call(path)
            self.assertEqual(code, 200)
            self.assertEqual(headers.get_content_type(), mime)
            self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.login()
        self.assertEqual(self.call('/../app/auth.py')[0], 404)


class DeskPersistence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'desk.sqlite3'
        self.addCleanup(self.temp.cleanup)

    def test_password_hash_session_expiry_reset_and_validation(self):
        auth.set_password(self.path, 'alice', PASSWORD)
        token = auth.login(self.path, 'alice', PASSWORD)
        with Database(self.path) as db:
            stored = db.connection.execute('SELECT password_hash FROM desk_users').fetchone()[0]
            self.assertNotIn(PASSWORD, stored)
            self.assertEqual(db.connection.execute('SELECT token_hash FROM login_sessions').fetchone()[0], hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(auth.identify(self.path, token), 'alice')
        with patch('app.auth.time.time', return_value=time.time() + auth.TTL + 1):
            self.assertIsNone(auth.identify(self.path, token))
        auth.set_password(self.path, 'alice', PASSWORD + '-new')
        self.assertIsNone(auth.identify(self.path, token))
        self.assertIsNone(auth.login(self.path, 'alice', PASSWORD))
        for username, password in (('bad username', PASSWORD), ('alice', 'short')):
            with self.assertRaises(ValueError):
                auth.set_password(self.path, username, password)

    def test_actor_audit_failure_rolls_back_allocation_and_session(self):
        with Database(self.path) as db:
            create_session(session_id='atomic', database=db)
            session_turn('atomic', expected_version=0, request_id='preview', message='Allocate ORD-045.', database=db)
            db.connection.execute("CREATE TRIGGER fail_actor BEFORE INSERT ON request_actors BEGIN SELECT RAISE(ABORT,'fail'); END")
            result = session_turn('atomic', expected_version=1, request_id='confirm', action='confirm', actor='operator', database=db)
            self.assertEqual(result['result']['reason_codes'], ['DB_ERROR'])
            self.assertEqual(inspect_order('ORD-045', database=db)['state'], 'READY')
            self.assertEqual(inspect_session('atomic', database=db)['version'], 1)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM requests WHERE request_id='confirm'").fetchone()[0], 0)

    def test_actor_bound_replay_conflict_does_not_attribute_to_second_user(self):
        create_session(session_id='s', db_path=self.path)
        kwargs = dict(expected_version=0, request_id='p', message='Allocate ORD-045.', db_path=self.path)
        session_turn('s', actor='alice', **kwargs)
        self.assertTrue(session_turn('s', actor='alice', **kwargs)['replayed'])
        self.assertEqual(session_turn('s', actor='bob', **kwargs)['result']['reason_codes'], ['IDEMPOTENCY_CONFLICT'])
        self.assertEqual(desk.audit(self.path)['items'][0]['actor'], 'alice')

    def test_v3_upgrade_preserves_session_and_allocation_and_rolls_back_failure(self):
        for fail in (False, True):
            path = Path(self.temp.name) / f'v3-{fail}.sqlite3'
            with Database(path) as db:
                process_request('Allocate ORD-045.', database=db, backend='offline')
                create_session(session_id='saved', database=db)
                session_turn('saved', expected_version=0, request_id='pending', message='Allocate cheapest.', database=db)
                before = inspect_order('ORD-045', database=db)
                saved = inspect_session('saved', database=db)
                for table in ('login_sessions', 'desk_users', 'request_actors'):
                    db.connection.execute('DROP TABLE ' + table)
                db.connection.execute('DELETE FROM schema_migrations WHERE version=4')
                if fail:
                    db.connection.execute("CREATE TRIGGER fail_v4 BEFORE INSERT ON schema_migrations WHEN NEW.version=4 BEGIN SELECT RAISE(ABORT,'fail'); END")
            if fail:
                with self.assertRaises(sqlite3.DatabaseError):
                    Database(path)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 3)
                    self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='desk_users'").fetchone())
            else:
                with Database(path) as db:
                    self.assertEqual(inspect_order('ORD-045', database=db), before)
                    self.assertEqual(inspect_session('saved', database=db), saved)
                    self.assertEqual(db.connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], DB_VERSION)
                    self.assertEqual(db.connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_csv_formula_safety_and_legacy_approver_is_not_invented(self):
        message = '=HYPERLINK("https://example.invalid")'
        raw = desk.audit_csv([{'original_message': message}]).decode('utf-8-sig')
        self.assertEqual(next(csv.DictReader(io.StringIO(raw)))['original_message'], "'" + message)
        process_request('Allocate ORD-045.', db_path=self.path, backend='offline')
        record = desk.audit(self.path)['items'][0]
        self.assertTrue(record['approved'])
        self.assertIsNone(record['approved_by'])

    def test_lapsed_and_reassigned_records_reflect_committed_state(self):
        process_request('Allocate ORD-045.', db_path=self.path, backend='offline')
        process_event('reassign', 'ORD-045', actor='operator', reason='New plan', expected_version=1,
                      event_id='reassign', preferred_workshop='W8', db_path=self.path)
        record = desk.audit(self.path, request_id='reassign')['items'][0]
        self.assertTrue(record['approved'])
        self.assertEqual(record['approved_by'], 'operator')
        process_event('lapse', 'ORD-045', actor='operator', reason='Terminated', expected_version=2,
                      event_id='lapse', db_path=self.path)
        dashboard = desk.dashboard(self.path, date(2026, 4, 1))
        self.assertEqual(dashboard['stats']['lapsed'], 1)
        self.assertNotIn('ORD-045', [o['order_id'] for w in dashboard['workshops'] for o in w['orders']])


if __name__ == '__main__':
    unittest.main()
