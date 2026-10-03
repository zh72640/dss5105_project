import itertools
import unittest
from datetime import date
from app.allocator.planner import plan
from app.schemas.parser_schema import ParseResult
from app.tools.models import Workshop


class IntegerPlanner(unittest.TestCase):
    def test_small_plans_match_exhaustive_optimum(self):
        shops=[Workshop('W1','A',3,1,.1,1.5,frozenset({'TOPS'}),'ACTIVE',4,0.,''),
               Workshop('W2','B',2,1,.02,.9,frozenset({'TOPS'}),'ACTIVE',5,.5,''),
               Workshop('W3','C',4,2,.05,1.1,frozenset({'TOPS'}),'ACTIVE',6,.2,'')]
        for pieces,limit,objective in itertools.product(range(1,11),(1,2,3),('min_cost','min_delay','min_defects')):
            order={'pieces':pieces,'category':'TOPS','due_date':'2026-04-30'}
            result=plan(order,shops,ParseResult(num_workshop_allowed=limit),objective,date(2026,4,1))
            scores=[]
            for quantities in itertools.product(*(range(w.max_batch+1) for w in shops)):
                if sum(quantities)!=pieces or sum(q>0 for q in quantities)>limit:
                    continue
                if objective=='min_cost': score=sum(q*w.cost for q,w in zip(quantities,shops))
                elif objective=='min_defects': score=sum(q*w.defect_rate for q,w in zip(quantities,shops))/pieces
                else: score=max(w.queue_days+w.lead_days+q/w.capacity for q,w in zip(quantities,shops) if q)
                scores.append(score)
            with self.subTest(pieces=pieces,limit=limit,objective=objective):
                self.assertEqual(result['success'],bool(scores))
                if scores:
                    self.assertAlmostEqual(result['score'],min(scores))
                    self.assertEqual(sum(p['pieces'] for p in result['allocation']),pieces)
                    self.assertLessEqual(len(result['allocation']),limit)

    def test_hard_deadline_cost_respects_queue_capacity(self):
        shops=[Workshop('W1','Cheap',100,1,.1,1.,frozenset({'TOPS'}),'ACTIVE',None,10.,''),
               Workshop('W2','Fast',100,1,.1,2.,frozenset({'TOPS'}),'ACTIVE',None,0.,'')]
        result=plan({'pieces':150,'category':'TOPS','due_date':'2026-04-04'},shops,
                    ParseResult(deadline_required=True,num_workshop_allowed=2),'min_cost',date(2026,4,1))
        self.assertTrue(result['success']); self.assertTrue(result['deadline_met'])
        self.assertEqual(result['allocation'][0]['workshop_id'],'W2')
