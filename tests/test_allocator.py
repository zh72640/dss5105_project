import itertools
import unittest
from datetime import date

from app.allocator import AllocationRequest, allocate
from app.schemas.business import Workshop


class IntegerPlanner(unittest.TestCase):
    def test_small_plans_match_exhaustive_optimum(self):
        shops = [Workshop('W1', 'A', 3, 1, .1, 1.5, frozenset({'TOPS'}), 'ACTIVE', 4, 0., ''),
                 Workshop('W2', 'B', 2, 1, .02, .9, frozenset({'TOPS'}), 'ACTIVE', 5, .5, ''),
                 Workshop('W3', 'C', 4, 2, .05, 1.1, frozenset({'TOPS'}), 'ACTIVE', 6, .2, '')]
        for pieces, limit, objective in itertools.product(range(1, 11), (1, 2, 3), ('min_cost', 'min_delay', 'min_defects')):
            order = {'pieces': pieces, 'category': 'TOPS', 'due_date': '2026-04-30'}
            result = allocate(AllocationRequest(
                order=order, workshops=shops, as_of=date(2026, 4, 1), objective=objective,
                max_workshops=limit))
            scores = []
            for quantities in itertools.product(*(range(w.max_batch + 1) for w in shops)):
                if sum(quantities) != pieces or sum(q > 0 for q in quantities) > limit:
                    continue
                if objective == 'min_cost':
                    score = sum(q * w.cost for q, w in zip(quantities, shops))
                elif objective == 'min_defects':
                    score = sum(q * w.defect_rate for q, w in zip(quantities, shops)) / pieces
                else:
                    score = max(w.queue_days + w.lead_days + q / w.capacity for q, w in zip(quantities, shops) if q)
                scores.append(score)
            with self.subTest(pieces=pieces, limit=limit, objective=objective):
                self.assertEqual(result['success'], bool(scores))
                if scores:
                    self.assertAlmostEqual(result['score'], min(scores))
                    self.assertEqual(sum(p['pieces'] for p in result['allocation']), pieces)
                    self.assertLessEqual(len(result['allocation']), limit)

    def test_hard_deadline_cost_respects_queue_capacity(self):
        shops = [Workshop('W1', 'Cheap', 100, 1, .1, 1., frozenset({'TOPS'}), 'ACTIVE', None, 10., ''),
                 Workshop('W2', 'Fast', 100, 1, .1, 2., frozenset({'TOPS'}), 'ACTIVE', None, 0., '')]
        result = allocate(AllocationRequest(
            order={'pieces': 150, 'category': 'TOPS', 'due_date': '2026-04-04'},
            workshops=shops, as_of=date(2026, 4, 1), objective='min_cost',
            deadline_required=True, max_workshops=2))
        self.assertTrue(result['success'])
        self.assertTrue(result['deadline_met'])
        self.assertEqual(result['allocation'][0]['workshop_id'], 'W2')

    def test_default_max_workshops_is_single(self):
        shops = [Workshop('W1', 'A', 3, 1, .1, 1.5, frozenset({'TOPS'}), 'ACTIVE', 4, 0., ''),
                 Workshop('W2', 'B', 2, 1, .02, .9, frozenset({'TOPS'}), 'ACTIVE', 5, .5, '')]
        # pieces=4 fits W1 alone; default max_workshops=1 must not enumerate a 2-workshop split.
        result = allocate(AllocationRequest(
            order={'pieces': 4, 'category': 'TOPS', 'due_date': '2026-04-30'},
            workshops=shops, as_of=date(2026, 4, 1), objective='min_cost'))
        self.assertTrue(result['success'])
        self.assertEqual(len(result['allocation']), 1)
        split = allocate(AllocationRequest(
            order={'pieces': 6, 'category': 'TOPS', 'due_date': '2026-04-30'},
            workshops=shops, as_of=date(2026, 4, 1), objective='min_cost', max_workshops=2))
        self.assertTrue(split['success'])
        self.assertEqual(len(split['allocation']), 2)

    def test_invalid_max_workshops_raises(self):
        shops = [Workshop('W1', 'A', 3, 1, .1, 1., frozenset({'TOPS'}), 'ACTIVE', None, 0., '')]
        with self.assertRaises(ValueError):
            allocate(AllocationRequest(
                order={'pieces': 1, 'category': 'TOPS', 'due_date': '2026-04-30'},
                workshops=shops, as_of=date(2026, 4, 1), objective='min_cost', max_workshops=0))
        with self.assertRaises(ValueError):
            allocate(AllocationRequest(
                order={'pieces': 1, 'category': 'TOPS', 'due_date': '2026-04-30'},
                workshops=shops, as_of=date(2026, 4, 1), objective='min_cost', max_workshops=9))


class PlanningMaxWorkshops(unittest.TestCase):
    def test_unsourced_limit_stays_single(self):
        from app.services.allocation import _planning_max_workshops
        self.assertEqual(_planning_max_workshops(3, sources=None), 1)
        self.assertEqual(_planning_max_workshops(3, sources={}), 1)
        self.assertEqual(_planning_max_workshops(3, sources={'objective': {}}), 1)

    def test_sourced_limit_enables_split(self):
        from app.services.allocation import _planning_max_workshops
        self.assertEqual(_planning_max_workshops(3, sources={'num_workshop_allowed': {}}), 3)
        self.assertEqual(_planning_max_workshops(1, sources={'num_workshop_allowed': {}}), 1)
