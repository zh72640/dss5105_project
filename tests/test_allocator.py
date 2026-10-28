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
        for pieces, limit, objective in itertools.product(range(1, 11), (1, 2, 3), ('min_cost', 'min_delay', 'min_defects', 'hybrid')):
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
                    if objective == 'hybrid':
                        score = .6 * score + .4 * 100 * sum(q * w.defect_rate for q, w in zip(quantities, shops)) / pieces
                scores.append(score)
            with self.subTest(pieces=pieces, limit=limit, objective=objective):
                self.assertEqual(result['success'], bool(scores))
                if scores:
                    self.assertAlmostEqual(result['score'], min(scores))
                    self.assertEqual(sum(p['pieces'] for p in result['allocation']), pieces)
                    self.assertLessEqual(len(result['allocation']), limit)

    def test_hybrid_optimizes_weighted_quality_instead_of_fastest_split(self):
        shops = [Workshop('W1', 'A', 200, 0, .9, 1., frozenset({'TOPS'}), 'ACTIVE', None, 0., ''),
                 Workshop('W2', 'B', 50, 0, 0., 2., frozenset({'TOPS'}), 'ACTIVE', 80, 0., '')]
        request = AllocationRequest(order={'pieces': 100, 'category': 'TOPS', 'due_date': '2026-04-04'},
                                    workshops=shops, as_of=date(2026, 4, 1), objective='hybrid', max_workshops=2)
        result = allocate(request)
        self.assertLessEqual(result['score'], 8.16 + 1e-10)
        self.assertEqual({p['workshop_id']: p['pieces'] for p in result['allocation']}, {'W1': 20, 'W2': 80})
        self.assertAlmostEqual(result['estimated_days'], 1.6)

    def test_hybrid_with_deadline_matches_exhaustive_feasible_solutions(self):
        shops = [Workshop('W1', 'A', 3, 0, .8, 1., frozenset({'TOPS'}), 'ACTIVE', 8, .5, ''),
                 Workshop('W2', 'B', 2, 1, .1, 2., frozenset({'TOPS'}), 'ACTIVE', 7, 0., '')]
        for pieces in range(1, 12):
            feasible = []
            for a in range(9):
                b = pieces - a
                if not 0 <= b <= 7:
                    continue
                used = [(w, q) for w, q in zip(shops, (a, b)) if q]
                days = max(w.queue_days + w.lead_days + q / w.capacity for w, q in used)
                if days <= 3:
                    feasible.append(.6 * days + 40 * sum(q * w.defect_rate for w, q in used) / pieces)
            result = allocate(AllocationRequest(
                order={'pieces': pieces, 'category': 'TOPS', 'due_date': '2026-04-04'},
                workshops=shops, as_of=date(2026, 4, 1), objective='hybrid',
                max_workshops=2, deadline_required=True))
            self.assertEqual(result['success'], bool(feasible))
            if feasible:
                self.assertAlmostEqual(result['score'], min(feasible))

    def test_full_candidate_plans_exist_when_every_plan_requires_a_split(self):
        shops = [Workshop('W1', 'A', 3, 1, .1, 1.5, frozenset({'TOPS'}), 'ACTIVE', 4, 0., ''),
                 Workshop('W2', 'B', 2, 1, .02, .9, frozenset({'TOPS'}), 'ACTIVE', 5, .5, ''),
                 Workshop('W3', 'C', 4, 2, .05, 1.1, frozenset({'TOPS'}), 'ACTIVE', 6, .2, '')]
        result = allocate(AllocationRequest(
            order={'pieces': 8, 'category': 'TOPS', 'due_date': '2026-04-30'},
            workshops=shops, as_of=date(2026, 4, 1), objective='min_delay', max_workshops=2))
        self.assertTrue(result['success'])
        self.assertEqual(result['candidate_ranking'], [])
        self.assertGreater(len(result['candidate_plans']), 0)
        self.assertEqual(result['candidate_plans'][0]['allocation'], result['allocation'])
        identities = []
        for candidate in result['candidate_plans']:
            self.assertEqual(sum(p['pieces'] for p in candidate['allocation']), 8)
            self.assertLessEqual(len(candidate['allocation']), 2)
            self.assertEqual(candidate['constraints']['max_workshops'], 2)
            identities.append(tuple(sorted((p['workshop_id'], p['pieces']) for p in candidate['allocation'])))
        self.assertEqual(len(set(identities)), len(identities))

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
        from app.services.allocation.service import _planning_max_workshops
        self.assertEqual(_planning_max_workshops(3, sources=None), 1)
        self.assertEqual(_planning_max_workshops(3, sources={}), 1)
        self.assertEqual(_planning_max_workshops(3, sources={'objective': {}}), 1)

    def test_sourced_limit_enables_split(self):
        from app.services.allocation.service import _planning_max_workshops
        self.assertEqual(_planning_max_workshops(3, sources={'num_workshop_allowed': {}}), 3)
        self.assertEqual(_planning_max_workshops(1, sources={'num_workshop_allowed': {}}), 1)
