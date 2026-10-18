"""Conditional options must be grounded and must never change authorization."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest

from app.db.database import Database
from app.schemas.business import Workshop
from app.services.allocation.alternatives import suggest
from app.services.chat import service as chat


class RefusalOptions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'options.sqlite3')

    def create(self, message):
        return chat.create(owner='alice', request_id='options-create', db_path=self.path,
                           as_of=date(2026, 4, 1), mode='offline', message=message)

    def test_required_suspended_workshop_has_grounded_authorization_options(self):
        result = self.create('Allocate ORD-045 to OldMill; exclude W3.')
        task = result['session']['task']
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(task['draft']['preferred_workshop'], 'W7')
        self.assertEqual(task['draft']['exclusion'], ['W3'])
        options = result['validation_report']['alternatives']
        self.assertTrue(options)
        for option in options:
            self.assertIn('preferred_workshop', option['required_changes'])
            self.assertIsNone(option['required_changes']['preferred_workshop'])
            self.assertTrue(option['requires_authorization'])
            self.assertFalse(option['committed'])
            self.assertEqual(option['effective_constraints']['exclusion'], ['W3'])
            self.assertTrue(all(part['workshop_id'] not in ('W3', 'W7') for part in option['plan']['allocation']))
            self.assertEqual(sum(part['pieces'] for part in option['plan']['allocation']), 150)
        self.assertIn('suggestion only', result['assistant_message']['content'])
        with Database(self.path) as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0], 0)
        revised = chat.turn(result['session_id'], owner='alice', request_id='authorize-alternative',
                            db_path=self.path, expected_version=result['session_version'],
                            message='clear preferred workshop')
        self.assertEqual(revised['task_state'], 'RECOMMENDED')
        self.assertFalse(revised['committed'])
        approved = chat.turn(result['session_id'], owner='alice', request_id='confirm-alternative',
                             db_path=self.path, expected_version=revised['session_version'],
                             action='confirm', recommendation_id=revised['recommendation_id'])
        self.assertTrue(approved['committed'])

    def test_hard_deadline_options_do_not_remove_the_original_deadline(self):
        with Database(self.path) as db:
            db.connection.execute("UPDATE orders SET due_date='2026-04-02' WHERE order_id='ORD-045'")
        result = self.create('Allocate ORD-045 fastest; must arrive on time; exclude W3.')
        self.assertFalse(result['committed'])
        self.assertTrue(result['session']['task']['draft']['deadline_required'])
        options = result['validation_report']['alternatives']
        self.assertTrue(options)
        for option in options:
            if not option['plan']['deadline_met']:
                self.assertIs(option['required_changes']['deadline_required'], False)
            self.assertNotIn('exclusion', option['required_changes'])
            self.assertTrue(all(p['workshop_id'] != 'W3' for p in option['plan']['allocation']))

    def test_all_excluded_has_no_fabricated_alternative(self):
        result = self.create('Allocate ORD-045; exclude W1, W2, W3, W4, W5, W6, W7, W8.')
        self.assertEqual(result['validation_report']['alternatives'], [])
        self.assertEqual(result['validation_report']['alternatives_status'], 'no_known_feasible_alternative')
        self.assertIn('No known feasible alternative', result['assistant_message']['content'])
        self.assertFalse(result['committed'])

    def test_split_proposal_is_explicit_and_preserves_remaining_quantity(self):
        shops = [Workshop('W1', 'A', 4, 0, .1, 1., frozenset({'TOPS'}), 'ACTIVE', 4, 0., ''),
                 Workshop('W2', 'B', 4, 0, .2, 2., frozenset({'TOPS'}), 'ACTIVE', 4, 0., '')]
        order = {'pieces': 10, 'completed_pieces': 2, 'category': 'TOPS', 'due_date': '2026-04-10'}
        constraints = {'objective': 'min_delay', 'num_workshop_allowed': 1,
                       'preferred_workshop': None, 'exclusion': [], 'deadline_required': False}
        before = deepcopy((order, constraints))
        options = suggest(order, shops, constraints, date(2026, 4, 1))
        self.assertEqual((order, constraints), before)
        self.assertEqual(options[0]['required_changes'], {'num_workshop_allowed': 2})
        self.assertEqual(options[0]['supported_mode'], 'offline')
        self.assertEqual(sum(p['pieces'] for p in options[0]['plan']['allocation']), 8)

    def test_missing_order_does_not_run_conditional_planning(self):
        result = self.create('Allocate cheapest.')
        self.assertNotIn('alternatives', result['validation_report'])
        self.assertIsNone(result['session']['recommendation'])
