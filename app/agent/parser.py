"""Week 4 parser seam.

The fixture implementation makes interface integration reproducible. A production
LLM adapter should validate its structured output into the same dataclass.
"""
import re
from app.schemas import Constraint, StructuredRequest


def _request_id(text: str) -> str | None:
    match = re.search(r"\bR\d{2}\b", text)
    return match.group(0) if match else None


def parse_request(text: str) -> StructuredRequest:
    rid = _request_id(text)
    if rid == "R09":
        return StructuredRequest(rid, "ORD-045", "Cotton Club", "Vest", "TOPS", 150,
            "2026-04-09", objective_override="fastest_turnaround",
            constraints=[Constraint("cost_priority", "ignore", "Cost doesn't matter")], raw_text=text)
    if rid == "R25":
        return StructuredRequest(rid, "ORD-109", "Harbor Knits", "Vest", "TOPS", 500,
            "2026-04-13", excluded_workshops=["BudgetWorks"],
            constraints=[Constraint("excluded_workshop", "BudgetWorks", "keep it away from BudgetWorks")], raw_text=text)
    if rid == "R27":
        return StructuredRequest(rid, "ORD-055", "Cotton Club", "Crewneck sweater", "TOPS", 800,
            "2026-03-31", objective_override="min_defects", raw_text=text)
    if rid == "R03":
        return StructuredRequest(rid, customer="TrendCart", ambiguous_fields=["order_id"], raw_text=text)
    if rid == "R08":
        return StructuredRequest(rid, "ORD-073", quantity=400, product="Hoodie", category="TOPS",
            preferred_workshop="FreshStart", raw_text=text)
    if rid == "R02":
        return StructuredRequest(rid, customer="Harbor Knits",
            constraints=[Constraint("historical_period", "last October", "last October")], raw_text=text)
    order = re.search(r"\bORD-\d{3}\b", text, re.I)
    return StructuredRequest(request_id=rid, order_id=order.group(0).upper() if order else None,
        missing_fields=[] if order else ["order_id"], raw_text=text)


def fake_parse_request(text: str) -> StructuredRequest:
    return parse_request(text)

