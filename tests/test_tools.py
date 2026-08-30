import unittest
from app.agent.parser import parse_request
from app.cli import request_text
from app.tools.orders import resolve_order
from app.tools.workshops import get_workshop
from app.tools.eligibility import exclusion_reason


class ToolTests(unittest.TestCase):
    def test_order_resolution(self):
        order, issue = resolve_order(parse_request(request_text("R09")))
        self.assertIsNone(issue)
        self.assertEqual(order.order_id, "ORD-045")

    def test_suspended_is_ineligible(self):
        self.assertEqual(exclusion_reason(get_workshop("OldMill"), "TOPS", 100, []), "status_suspended")

    def test_cap_is_ineligible(self):
        self.assertEqual(exclusion_reason(get_workshop("FreshStart"), "TOPS", 400, []),
                         "exceeds_300_piece_limit")


if __name__ == "__main__":
    unittest.main()

