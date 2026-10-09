import json
import unittest
from unittest.mock import patch

from app.agent.parser import ParserOutcome
from app.assistant_reply import allocation_reply
from app.db.database import Database
from app.schemas.parser_schema import ParseResult
from app.sessions import create_session, inspect_session, session_turn


class AssistantDesk(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.close)
        create_session(session_id="a", database=self.db)
        self.count = 0

    def turn(self, message="", **kwargs):
        self.count += 1
        return session_turn("a", message=message, database=self.db, request_id=f"r{self.count}",
                            expected_version=inspect_session("a", database=self.db)["version"], **kwargs)

    def test_missing_order_has_question_and_form_can_resolve_it(self):
        r = self.turn("Allocate at the lowest cost.")
        self.assertEqual(r["result"]["clarifications"][0]["field"], "order_id")
        self.assertIn("ORD-045", r["result"]["message"])
        r = self.turn(changes={"order_id": "ORD-045"})
        self.assertEqual(r["result"]["decision_status"], "REVIEW")
        self.assertIn("awaiting your approval", r["result"]["assistant_reply"])
        self.assertEqual(self.db.connection.execute("SELECT state FROM orders WHERE order_id='ORD-045'").fetchone()[0], "READY")

    def test_summary_exactly_matches_proposal_and_committed_result(self):
        preview = self.turn("Allocate ORD-045 cheapest.")
        committed = self.turn(action="confirm")
        for r in (preview, committed):
            text = r["result"]["assistant_reply"]
            self.assertIn("ORD-045", text)
            self.assertIn(str(r["result"]["allocation"][0]["pieces"]), text)
            self.assertIn(r["result"]["allocation"][0]["workshop_name"], text)
            self.assertIn(r["result"]["estimated_delivery_date"], text)
        self.assertIn("Approved and saved", committed["result"]["assistant_reply"])
        session = inspect_session("a", database=self.db)
        self.assertEqual(session["messages"][-1]["content"], committed["result"]["assistant_reply"])

    def test_form_resolves_objective_without_dropping_exclusions(self):
        self.turn("Allocate ORD-045 cheapest and fastest; exclude W3.")
        result = self.turn(changes={"objective": "min_cost"})
        self.assertFalse(result["session"]["blockers"])
        self.assertEqual(result["parsed"]["exclusion"], ["W3"])

    def test_conflicting_order_field_names_actual_registered_value(self):
        result = self.turn("Allocate ORD-045 999 pieces.")
        question = result["result"]["clarifications"][0]
        self.assertEqual(question["field"], "pieces")
        self.assertIn("150", question["help"])
        result = self.turn(changes={"pieces": None})
        self.assertEqual(sum(a["pieces"] for a in result["result"]["allocation"]), 150)

    def test_unsupported_requirement_stays_blocked_after_unrelated_edit(self):
        self.turn("Allocate ORD-045 with a budget of 100.")
        result = self.turn(changes={"objective": "min_cost"})
        self.assertIn("unsupported_constraint", result["session"]["blockers"])
        self.assertFalse(self.turn(action="confirm")["committed"])

    def test_invalid_edits_do_not_mutate_or_bypass_order_switch(self):
        self.turn("Allocate ORD-045.")
        old = inspect_session("a", database=self.db)
        for changes in ({"pieces": True}, {"deadline_required": "false"}, {"num_workshop_allowed": 9},
                        {"actor": "boss"}, {"exclusion": "W3"}, {"due_date": "2026-02-30"}, {}):
            result = self.turn(changes=changes)
            self.assertIn("INVALID_ARGUMENT", result["result"]["reason_codes"])
            self.assertEqual(inspect_session("a", database=self.db), old)
        result = self.turn(changes={"order_id": "ORD-109"})
        self.assertIn("ORDER_SWITCH_REQUIRES_NEW_SESSION", result["session"]["blockers"])

    def test_structured_edits_replay_without_second_write(self):
        self.turn("Allocate ORD-045.")
        kwargs = dict(changes={"objective": "min_cost", "exclusion": ["W3"]}, database=self.db,
                      expected_version=1, request_id="same-form", actor="boss")
        first = session_turn("a", **kwargs)
        replay = session_turn("a", **kwargs)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["session"]["version"], replay["session"]["version"])
        reordered = session_turn("a", **{**kwargs, "changes": {"exclusion": ["W3"], "objective": "min_cost"}})
        self.assertTrue(reordered["replayed"])
        conflict = session_turn("a", **{**kwargs, "changes": {"objective": "min_delay"}})
        self.assertIn("IDEMPOTENCY_CONFLICT", conflict["result"]["reason_codes"])

    def test_deepseek_addition_keeps_existing_constraints(self):
        self.turn("Allocate ORD-045 cheapest; exclude W3.")
        self.db.connection.execute("UPDATE sessions SET backend='deepseek' WHERE session_id='a'")
        parsed = ParseResult(objective="min_delay", preferred_workshop="W6", missing_fields=["order_id"])
        with patch("app.sessions.parse_with_telemetry", return_value=ParserOutcome(parsed, {"backend":"deepseek"})):
            result = self.turn("Please prioritize speed and use W6 for this order.")
        self.assertEqual(result["parsed"]["order_id"], "ORD-045")
        self.assertEqual(result["parsed"]["exclusion"], ["W3"])
        self.assertEqual(result["parsed"]["preferred_workshop"], "W6")
        self.assertEqual(result["parsed"]["objective"], "min_delay")
        self.assertEqual(result["session"]["state"], "ACTIVE")

    def test_service_error_is_not_reported_as_missing_order_details(self):
        self.db.connection.execute("UPDATE sessions SET backend='deepseek' WHERE session_id='a'")
        outcome = ParserOutcome(None, {"backend":"deepseek"}, "deepseek_api_key_missing")
        with patch("app.sessions.parse_with_telemetry", return_value=outcome):
            result = self.turn("Allocate ORD-045.")
        self.assertEqual(result["result"]["clarifications"][0]["field"], "service")
        self.assertIn("API key", result["result"]["message"])
        # The form is a real offline route even in a DeepSeek session.
        with patch("app.sessions.parse_with_telemetry", side_effect=AssertionError("Unexpected model call")):
            result = self.turn(changes={"order_id": "ORD-045", "objective": "min_cost"})
        self.assertEqual(result["session"]["state"], "ACTIVE")

    def test_split_reply_includes_every_workshop_and_late_warning(self):
        result = {"success":True,"allocation":[{"pieces":10,"workshop_name":"One","workshop_id":"W1"},
                  {"pieces":20,"workshop_name":"Two","workshop_id":"W2"}],"estimated_cost":42,
                  "estimated_delivery_date":"2026-04-09","objective":"min_cost","warnings":["ESTIMATED_DEADLINE_MISS"]}
        reply = allocation_reply(result, "ORD-045")
        for text in ("30 pieces", "10 pieces to One", "20 pieces to Two", "42.00", "later than"):
            self.assertIn(text, reply)

    def test_ineligible_preference_explains_how_to_choose_an_alternative(self):
        result = self.turn("Allocate ORD-045 to W7.")
        question = result["result"]["clarifications"][0]
        self.assertEqual(question["field"], "preferred_workshop")
        self.assertIn("suspended", question["question"])
        self.assertIn("Any eligible workshop", question["help"])
        result = self.turn(changes={"preferred_workshop": None})
        self.assertTrue(result["result"]["success"])


if __name__ == "__main__":
    unittest.main()
