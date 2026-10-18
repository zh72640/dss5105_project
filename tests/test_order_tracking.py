"""Trace real approvals and production transitions without inventing milestones."""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.db.database import Database
from app.services.allocation.dispatch import seed_allocation
from app.services.production.lifecycle import inspect_order, process_event
from app.services.chat import service as chat


class OrderTracking(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'tracking.sqlite3')
        with Database(self.path):
            pass

    def inspect(self):
        return inspect_order('ORD-045', db_path=self.path)

    def allocate(self, request_id='allocation'):
        result = seed_allocation('Allocate ORD-045 to Nimble Needle.', db_path=self.path,
                                 request_id=request_id, actor='dispatcher')
        self.assertTrue(result['result']['success'])
        return result

    def event(self, action, event_id, **extra):
        result = process_event(action, 'ORD-045', actor='operator', reason='Recorded production update',
                               expected_version=self.inspect()['version'], event_id=event_id,
                               as_of=date(2026, 4, 1), db_path=self.path, **extra)
        self.assertTrue(result['result']['success'], result)
        return result

    def test_ready_order_and_private_preview_do_not_claim_approval(self):
        chat.create(owner='private-owner', request_id='preview', mode='offline',
                    message='Allocate ORD-045.', db_path=self.path, as_of=date(2026, 4, 1))
        t = self.inspect()['tracking']
        self.assertEqual(t['current'], 'awaiting_allocation')
        self.assertEqual(t['events'], [])
        self.assertEqual(t['progress_percent'], 0)
        self.assertEqual([s['status'] for s in t['stages']], ['done', 'current', 'pending', 'pending'])

    def test_approval_is_distinct_from_recorded_production(self):
        self.allocate()
        t = self.inspect()['tracking']
        self.assertEqual(t['current'], 'allocated')
        self.assertEqual(t['stages'][2]['status'], 'pending')
        self.assertEqual(t['events'][0]['actor'], 'dispatcher')
        self.assertEqual(t['events'][0]['allocation'], [{'workshop_id': 'W6', 'pieces': 150}])

    def test_partial_completion_cancel_reassign_completion_and_replay(self):
        self.allocate()
        self.event('complete', 'partial', workshop_id='W6', pieces=50)
        self.assertEqual(self.inspect()['tracking']['current'], 'production')
        self.event('cancel', 'cancel')
        cancelled = self.inspect()['tracking']
        self.assertEqual(cancelled['current'], 'awaiting_allocation')
        self.assertEqual(cancelled['completed_pieces'], 50)
        self.assertEqual(cancelled['stages'][2]['status'], 'paused')
        self.allocate('allocate-again')
        self.event('reassign', 'reassign', preferred_workshop='W8')
        version = self.inspect()['version']
        self.event('complete', 'final', workshop_id='W8', pieces=100)
        replay = process_event('complete', 'ORD-045', actor='operator', reason='Recorded production update',
                               expected_version=version, event_id='final', workshop_id='W8', pieces=100,
                               as_of=date(2026, 4, 1), db_path=self.path)
        self.assertTrue(replay['replayed'])
        t = self.inspect()['tracking']
        self.assertEqual([e['action'] for e in t['events']], ['allocate', 'complete', 'cancel', 'allocate', 'reassign', 'complete'])
        self.assertEqual(sum(e['completed_delta'] for e in t['events']), 150)
        self.assertEqual(t['events'][-1]['workshop_id'], 'W8')
        self.assertEqual(t['progress_percent'], 100)
        self.assertEqual(t['stages'][-1]['status'], 'current')

    def test_rejected_attempt_does_not_move_the_journey(self):
        self.allocate()
        process_event('complete', 'ORD-045', actor='operator', reason='stale attempt', expected_version=0,
                      event_id='rejected', workshop_id='W6', pieces=1, db_path=self.path)
        t = self.inspect()['tracking']
        self.assertEqual(len(t['events']), 1)
        self.assertEqual(len(t['attempts']), 1)
        self.assertEqual(t['attempts'][0]['completed_delta'], 0)
        self.assertFalse(t['attempts'][0]['applied'])
        self.assertEqual(t['current'], 'allocated')

    def test_lapse_does_not_look_completed(self):
        self.allocate()
        self.event('complete', 'partial', workshop_id='W6', pieces=25)
        self.event('lapse', 'lapse')
        t = self.inspect()['tracking']
        self.assertEqual(t['current'], 'lapsed')
        self.assertEqual(t['stages'][-1]['status'], 'blocked')
        self.assertEqual(t['completed_pieces'], 25)

    def test_imported_completion_does_not_invent_intermediate_events(self):
        with Database(self.path) as db:
            oid = db.connection.execute("SELECT order_id FROM orders WHERE state='COMPLETED' LIMIT 1").fetchone()[0]
        t = inspect_order(oid, db_path=self.path)['tracking']
        self.assertEqual(t['current'], 'completed')
        self.assertEqual([s['status'] for s in t['stages']], ['done', 'unknown', 'unknown', 'current'])
        self.assertEqual(t['events'], [])
        self.assertTrue(t['history_note'])

    def test_complete_history_is_not_limited_to_thirty_recent_events(self):
        for n in range(16):
            self.allocate(f'allocate-{n}')
            self.event('cancel', f'cancel-{n}')
        self.assertEqual(len(self.inspect()['tracking']['events']), 32)
        self.assertEqual(self.inspect()['tracking']['events'][0]['id'], 'allocate-0')

    def test_repeated_inspection_does_not_write_business_state(self):
        self.allocate()
        before = self.inspect()
        for _ in range(3):
            self.assertEqual(self.inspect(), before)
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 1)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)
        self.assertIsNone(inspect_order('MISSING', db_path=self.path))
