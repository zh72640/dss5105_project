"""The imported policy agrees with zhen's reference and preserves guarded commits."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.allocator import AllocationRequest, allocate
from app.db.database import Database
from app.schemas.business import Workshop
from app.services.allocation.contracts import saved_result
from app.services.chat import service as chat
from app.services.intake.rule_parser import extract
from evaluation.simulator_adapter import make_allocator
from harness import simulate_new as reference


class WeightedPolicy(unittest.TestCase):
    def test_matches_source_policy_on_all_registered_batches_and_queue_snapshots(self):
        workshops = reference.load_workshops()
        production = make_allocator('weighted_hybrid')
        for batch in reference.load_batches():
            for shift in (0, 3, 15):
                queues = {wid: w.queue0 + shift * (i % 3) for i, (wid, w) in enumerate(workshops.items())}
                with self.subTest(order=batch['order_id'], shift=shift):
                    self.assertEqual(production(batch, workshops, queues),
                                     reference.weighted_hybrid_score(batch, workshops, queues))

    def request(self, workshops=None, **kwargs):
        shops = workshops or [Workshop('W1', 'One', 100, 1, .05, 5., frozenset({'TOPS'}),
                                        'ACTIVE', None, 0., '')]
        return AllocationRequest(order={'pieces': 100, 'category': 'TOPS', 'due_date': '2026-04-10'},
                                 workshops=shops, as_of=date(2026, 4, 1), objective='weighted_hybrid', **kwargs)

    def test_constant_ranges_and_single_candidate_do_not_divide_by_zero(self):
        first = self.request().workshops[0]
        result = allocate(self.request([first, replace(first, workshop_id='W2')]))
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['recommended_workshop_id'], 'W1')
        self.assertTrue(all(p['score'] == 0 for p in result['candidate_ranking']))
        self.assertEqual(allocate(self.request())['score'], 0)

    def test_status_exclusions_batch_cap_deadline_and_required_workshop_constrain_pool(self):
        first = self.request().workshops[0]
        shops = [first, replace(first, workshop_id='W2', status='SUSPENDED'),
                 replace(first, workshop_id='W3', max_batch=50),
                 replace(first, workshop_id='W4', queue_days=30),
                 replace(first, workshop_id='W5'), replace(first, workshop_id='W6', makes=frozenset({'ACCESSORIES'}))]
        result = allocate(self.request(shops, exclusion=['W5'], deadline_required=True))
        self.assertEqual([p['workshop_id'] for p in result['candidate_ranking']], ['W1'])
        self.assertEqual(set(result['rejected']), {'W2', 'W3', 'W5', 'W6'})
        required = allocate(self.request(shops, preferred_workshop='W4'))
        self.assertEqual(required['recommended_workshop_id'], 'W4')
        self.assertEqual(required['score'], 0)
        self.assertIn('Required sole workshop', required['explanation_evidence']['selection_reason'])

    def test_split_is_explicitly_blocked_and_no_candidate_is_not_a_model_failure(self):
        result = allocate(self.request(max_workshops=2))
        self.assertFalse(result['success'])
        self.assertIn('WEIGHTED_HYBRID_SINGLE_WORKSHOP_ONLY', result['reason_codes'])
        result = allocate(self.request(exclusion=['W1']))
        self.assertFalse(result['success'])
        self.assertIn('NO_ELIGIBLE_WORKSHOP', result['reason_codes'])

    def test_existing_hybrid_and_new_policy_are_distinct_in_intake(self):
        for text, expected in [('Allocate ORD-045 using hybrid.', 'hybrid'),
                               ('Allocate ORD-045 using weighted hybrid.', 'weighted_hybrid'),
                               ('Allocate ORD-045 using normalized 80/20.', 'weighted_hybrid'),
                               ('Allocate ORD-045 with 80% lateness and 20% defect exposure.', 'weighted_hybrid')]:
            with self.subTest(text=text):
                parsed = extract(text, date(2026, 4, 1))
                self.assertEqual(parsed['objective'], expected)
                self.assertNotIn(parsed.get('num_workshop_allowed'), (20, 80))

    def test_chat_preview_evidence_is_saved_and_commit_remains_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder)/'weighted.sqlite3')
            created = chat.create(owner='alice', request_id='new', db_path=db, as_of=date(2026, 4, 1),
                                  mode='offline', message='Allocate ORD-045 using weighted hybrid.')
            sid = created['session_id']
            session = chat.inspect(sid, owner='alice', db_path=db)
            rec = session['recommendation']
            self.assertEqual(rec['result']['objective'], 'weighted_hybrid')
            evidence = saved_result(rec)['explanation_evidence']
            self.assertTrue(evidence['candidates'])
            self.assertIn('0.8', evidence['score_formula'])
            before = deepcopy(rec['result'])
            with Database(db) as connection:
                self.assertEqual(connection.connection.execute("SELECT COUNT(*) FROM working_order WHERE order_id='ORD-045'").fetchone()[0], 0)
            reply = chat.turn(sid, owner='alice', request_id='confirm', expected_version=session['version'],
                              db_path=db, action='confirm', recommendation_id=rec['recommendation_id'])
            self.assertTrue(reply['committed'])
            replay = chat.turn(sid, owner='alice', request_id='confirm', expected_version=session['version'],
                               db_path=db, action='confirm', recommendation_id=rec['recommendation_id'])
            self.assertTrue(replay['replayed'])
            self.assertEqual(reply['recommendation_id'], replay['recommendation_id'])
            self.assertEqual(before, chat.inspect(sid, owner='alice', db_path=db)['recommendation']['result'])


if __name__ == '__main__':
    unittest.main()
