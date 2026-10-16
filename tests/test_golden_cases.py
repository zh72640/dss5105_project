import unittest
from app.cli.dispatch import request_text
from app.services.allocation.dispatch import seed_allocation


class GoldenCases(unittest.TestCase):
    def status(self, rid):
        return seed_allocation(request_text(rid))["result"]["decision_status"]

    def test_r09_allocates(self):
        payload = seed_allocation(request_text("R09"))
        self.assertEqual(payload["result"]["decision_status"], "ALLOCATE")
        self.assertTrue(payload["result"]["recommended_workshop_id"])

    def test_r03_clarifies(self):
        self.assertEqual(self.status("R03"), "CLARIFY")

    def test_r08_refuses_trial_limit(self):
        payload = seed_allocation(request_text("R08"))
        self.assertEqual(payload["result"]["decision_status"], "REFUSE")
        self.assertIn("EXCEEDS_300_PIECE_LIMIT", payload["result"]["reason_codes"])

    def test_r02_declines_missing_history(self):
        self.assertEqual(self.status("R02"), "DECLINE")

    def test_r25_honours_exclusion(self):
        payload = seed_allocation(request_text("R25"))
        names = [x["workshop_name"] for x in payload["result"]["candidate_ranking"]]
        self.assertNotIn("BudgetWorks", names)


if __name__ == "__main__":
    unittest.main()
