"""Recorded demo inputs resume safely and preserve grounded special constraints."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from app.schemas.chat import TurnInterpretation
from app.services.chat import service as chat
from app.services.chat.constraint_patches import apply_interpretation
from tests.test_allocation_node import ExtractionScript, actions
from tests.test_architecture_alignment import NativeScript


class ClarificationRecovery(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = str(Path(self.folder.name) / 'clarification.sqlite3')
        created = chat.create(owner='alice', request_id='new', db_path=self.db,
                              as_of=date(2026, 4, 1), mode='llm')
        self.sid = created['session_id']
        self.task = created['session']['task']

    def test_missing_order_followed_by_valid_id_produces_a_preview_and_replays(self):
        missing = ExtractionScript(malformed=json.dumps({'intent': 'allocate_request',
            'patch_operations': [], 'ambiguity_reason': 'No order reference was provided; specify which order to allocate.'}))
        blocked = chat.turn(self.sid, owner='alice', request_id='missing', expected_version=0,
            db_path=self.db, message='Please allocate an order.', registry=missing)
        self.assertIsNone(blocked['recommendation_id'])
        self.assertIn('Which order would you like to allocate?', blocked['assistant_message']['content'])
        self.assertFalse(missing.offered)
        model = NativeScript(actions=actions())
        args = dict(owner='alice', request_id='answer', expected_version=blocked['session_version'],
                    db_path=self.db, message='Allocate ORD-045.', registry=model)
        response = chat.turn(self.sid, **args)
        self.assertIsNotNone(response['recommendation_id'])
        self.assertFalse(response['committed'])
        self.assertEqual(response['allocation']['order_id'], 'ORD-045')
        self.assertEqual(len(model.offered), 3)
        replay = chat.turn(self.sid, **args)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['recommendation_id'], response['recommendation_id'])
        self.assertEqual(len(model.offered), 3)

    def test_legacy_missing_reference_clears_but_other_blockers_remain(self):
        task = deepcopy(self.task)
        task['issues'] = [
            {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'question': 'No order reference provided.'},
            {'code': 'AMBIGUOUS_MESSAGE', 'field': 'message', 'question': 'No order reference provided, and the budget is unclear.'},
            {'code': 'unsupported_constraint', 'field': 'unsupported', 'question': 'The budget is unsupported.'},
        ]
        patch = TurnInterpretation(intent='answer_clarification', patch_operations=[{
            'op': 'set', 'field': 'order_id', 'value': 'ORD-045',
            'evidence': {'message_sequence': 2, 'quote': 'Allocate ORD-045.'}}])
        revised = apply_interpretation(task, patch, 2)
        self.assertEqual(len(revised['issues']), 2)
        self.assertIn('budget', revised['issues'][0]['question'])
        self.assertEqual(revised['issues'][1]['code'], 'unsupported_constraint')
        self.assertEqual(len(task['issues']), 3)

    def test_scalar_exclusion_reaches_weighted_preview_as_a_workshop_list(self):
        model = ExtractionScript(order_id='ORD-041', actions=actions(), patches=[
            ('objective', 'weighted_hybrid'), ('num_workshop_allowed', 1), ('exclusion', 'W6')])
        response = chat.turn(self.sid, owner='alice', request_id='special', expected_version=0,
            db_path=self.db, message='Allocate ORD-041 using weighted hybrid to one workshop. Exclude W6.',
            registry=model)
        self.assertIsNotNone(response['recommendation_id'])
        self.assertFalse(response['committed'])
        self.assertEqual(response['session']['task']['draft']['exclusion'], ['W6'])
        result = response['session']['recommendation']['result']
        self.assertEqual(result['objective'], 'weighted_hybrid')
        self.assertTrue(all(part['workshop_id'] != 'W6' for part in result['allocation']))
        self.assertEqual(len(model.offered), 3)


if __name__ == '__main__':
    unittest.main()
