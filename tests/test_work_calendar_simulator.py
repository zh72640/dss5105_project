import math
import unittest
from datetime import date

from evaluation.compare_work_calendars import ProductionCalendar, compare, BASELINES, OBJECTIVES


class ProductionCalendarTests(unittest.TestCase):
    def setUp(self):
        self.calendar = ProductionCalendar(date(2026, 4, 4), sunday_off=True)  # Saturday

    def test_saturday_work_crosses_sunday_without_production(self):
        self.assertEqual(self.calendar.finish(0, 2), 3)  # Saturday + Monday
        self.assertEqual(self.calendar.finish(0.5, 1), 2.5)
        self.assertEqual(self.calendar.working_time(1, 2), 0)

    def test_sunday_arrival_waits_until_monday(self):
        self.assertEqual(self.calendar.finish(1.25, 0.5), 2.5)
        self.assertEqual(self.calendar.finish(1.25, 0), 1.25)

    def test_exact_saturday_finish_does_not_add_a_rest_day(self):
        self.assertEqual(self.calendar.finish(0, 1), 1)
        self.assertEqual(self.calendar.finish(0, 6), 7)
        self.assertEqual(self.calendar.finish(0, 7), 8)
        self.assertEqual(self.calendar.finish(0, 1 + 1e-14), 1)

    def test_calendar_conserves_requested_production_across_multiple_weeks(self):
        for start in (0, 0.75, 1, 1.9, 2, 8.5):
            for days in (0, 0.125, 1, 6, 14.5, 120):
                with self.subTest(start=start, days=days):
                    finish = self.calendar.finish(start, days)
                    self.assertAlmostEqual(self.calendar.working_time(start, finish), days)
                    if days:
                        # The instant before completion must be on a production day.
                        self.assertFalse(self.calendar.closed(math.floor(finish - 1e-9)))

    def test_seven_day_calendar_has_no_weekend_adjustment(self):
        calendar = ProductionCalendar(date(2026, 4, 4), sunday_off=False)
        self.assertEqual(calendar.finish(0.5, 2), 2.5)
        self.assertEqual(calendar.working_time(0.5, 2.5), 2)

    def test_all_policies_reproduce_official_outputs_before_calendar_change(self):
        report = compare()
        policies = set(BASELINES) | {'planner_' + objective for objective in OBJECTIVES}
        expected = {(scenario, policy) for scenario in ('seven_day', 'sunday_off') for policy in policies}
        self.assertEqual({(r['scenario'], r['policy']) for r in report['runs']}, expected)
        self.assertEqual(len(report['runs']), len(expected))
        for row in report["runs"]:
            self.assertEqual(row["metrics"]["batches"], 120)
            self.assertEqual(len({x["order_id"] for x in row["outcomes"]}), 120)


if __name__ == "__main__":
    unittest.main()
