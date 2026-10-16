"""Order retrieval and eligibility through the current SQLite tools."""
import unittest
from datetime import date
from app.cli.dispatch import request_text
from app.db.database import Database
from app.db.order_repository import retrieve
from app.db.workshop_repository import get_all
from app.schemas.parser_schema import ParseResult
from app.allocator import exclusion_reason
from app.services.intake.rule_parser import extract


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.db = self.enterContext(Database(":memory:"))
        self.workshops = {w.name: w for w in get_all(self.db.connection, date(2026, 4, 1))}

    def test_order_resolution(self):
        parsed = ParseResult(**extract(request_text("R09"), date(2026, 4, 1)))
        order, issue = retrieve(self.db.connection, parsed)
        self.assertIsNone(issue)
        self.assertEqual(order["order_id"], "ORD-045")

    def test_suspended_is_ineligible(self):
        self.assertEqual(exclusion_reason(self.workshops["OldMill"], "TOPS", 100, []), "status_suspended")

    def test_cap_is_ineligible(self):
        self.assertEqual(exclusion_reason(self.workshops["FreshStart"], "TOPS", 400, []),
                         "exceeds_300_piece_limit")


if __name__ == "__main__":
    unittest.main()
