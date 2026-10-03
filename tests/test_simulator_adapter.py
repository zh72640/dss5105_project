import unittest
from copy import deepcopy
from datetime import date
from evaluation.compare_simulator import compare, summarize
from evaluation.simulator_adapter import make_allocator
from harness.simulate import Simulator, eligible_workshops, load_workshops


class SimulatorAdapter(unittest.TestCase):
    def test_reports_match_official_metrics_and_preserve_inputs(self):
        outcomes = [{"turnaround": float(i), "pieces": 10, "workshop": "W1" if i < 5 else "W2",
                     "late": i >= 8, "defective": i == 0, "cost": 12.} for i in range(10)]
        self.assertEqual(summarize(outcomes), {"batches":10,"mean_days":4.5,"p90_days":9.,"late_percent":20.,
                                             "defect_percent":10.,"total_cost":120.,"max_share_percent":50.})
        workshops = load_workshops()
        queues = {wid: w.queue0 for wid, w in workshops.items()}
        batch = {"order_id":"TEST","pieces":150,"category":"TOPS","sent_date":date(2026,4,1),"due_date":date(2026,4,9)}
        before = deepcopy((workshops, queues, batch))
        for objective in ("min_delay", "min_cost", "min_defects", "hybrid"):
            choice = make_allocator(objective)(batch, workshops, queues)
            self.assertIn(choice, [w.workshop_id for w in eligible_workshops(batch, workshops)])
        self.assertEqual(before, (workshops, queues, batch))

    def test_official_runs_are_repeatable_complete_and_report_losses(self):
        report = compare()
        self.assertEqual(report, compare())
        self.assertEqual(len(report["runs"]), 14)
        self.assertEqual(len(report["comparisons"]), 24)
        self.assertTrue(report["primary_per_order_losses"])
        for run in report["runs"]:
            self.assertEqual(run["metrics"]["batches"], 120)
            self.assertEqual(len({r["order_id"] for r in run["outcomes"]}), 120)
        # A dominant workshop's queue must affect a speed choice.
        sim = Simulator()
        batch = sim.batches[0]
        queues = {wid: 0. for wid in sim.workshops}
        allocate = make_allocator("min_delay")
        first = allocate(batch, sim.workshops, queues)
        queues[first] = 10000.
        self.assertNotEqual(first, allocate(batch, sim.workshops, queues))
