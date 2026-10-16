"""Explicit form edits and conservative merging of validated follow-up fields."""
import re
from datetime import date
from app.schemas.parser_schema import OBJECTIVES

TEXT_FIELDS = {"customer", "product", "category", "order_date", "due_date", "preferred_workshop"}
EDIT_FIELDS = TEXT_FIELDS | {"order_id", "pieces", "objective", "num_workshop_allowed", "exclusion", "deadline_required"}
RESOLVED = {
    "order_id": {"order_id", "multiple_order_ids"},
    "objective": {"conflicting_objective", "negated_objective"},
    "num_workshop_allowed": {"conflicting_workshop_limit", "invalid_num_workshop_allowed"},
    "due_date": {"relative_due_date", "conflicting_due_date", "invalid_date", "due_before_order_date"},
    "order_date": {"conflicting_order_date", "invalid_date", "due_before_order_date"},
    "pieces": {"conflicting_pieces", "invalid_pieces"},
    "product": {"conflicting_products"}, "category": {"conflicting_category"},
    "preferred_workshop": {"unknown_workshop_name", "unclear_workshop_constraint", "multiple_preferred_workshops", "preferred_workshop_excluded"},
    "exclusion": {"negated_exclusion", "preferred_workshop_excluded"},
}


def valid_changes(changes):
    if not isinstance(changes, dict) or not changes or set(changes) - EDIT_FIELDS:
        return False
    for key, value in changes.items():
        if key == "order_id":
            if not isinstance(value, str) or not re.fullmatch(r"ORD-\d+|O\d+", value):
                return False
        elif key in ("pieces", "num_workshop_allowed"):
            if value is not None and (type(value) is not int or value <= 0 or (key == "num_workshop_allowed" and value > 8)):
                return False
        elif key == "objective":
            if value not in OBJECTIVES:
                return False
        elif key == "exclusion":
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(v, str) or not re.fullmatch(r"W[1-9]\d*", v) for v in value):
                return False
        elif key == "deadline_required":
            if type(value) is not bool:
                return False
        elif value is not None:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
                return False
            if key.endswith("date"):
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        return False
                except ValueError:
                    return False
            if key == "category" and value not in ("TOPS", "ACCESSORIES"):
                return False
            if key == "preferred_workshop" and not re.fullmatch(r"W[1-9]\d*", value):
                return False
    return True


def apply_changes(draft, changes):
    if draft["order_id"] and changes.get("order_id", draft["order_id"]) != draft["order_id"]:
        return None, "ORDER_SWITCH_REQUIRES_NEW_SESSION"
    out = {**draft, **changes}
    resolved = set().union(*(RESOLVED.get(k, set()) for k in changes))
    out["ambiguities"] = [v for v in draft["ambiguities"] if v not in resolved]
    out["missing_fields"] = [v for v in draft["missing_fields"] if v not in changes]
    if not out["order_id"] and "order_id" not in out["missing_fields"]:
        out["missing_fields"].append("order_id")
    if out["preferred_workshop"] and out["preferred_workshop"] in out["exclusion"]:
        out["ambiguities"].append("preferred_workshop_excluded")
    if out["due_date"] and out["order_date"] and out["due_date"] < out["order_date"]:
        out["ambiguities"].append("due_before_order_date")
    out["ambiguities"] = sorted(set(out["ambiguities"]))
    out["exclusion"] = sorted(set(out["exclusion"]))
    out["parse_status"] = "needs_clarification" if out["missing_fields"] or out["ambiguities"] else "ok"
    return out, None


def merge_followup(draft, parsed):
    values = parsed.to_dict()
    changes = {key: values[key] for key in EDIT_FIELDS - {"exclusion", "deadline_required"} if values[key] is not None}
    if values["exclusion"]:
        changes["exclusion"] = sorted(set(draft["exclusion"]) | set(values["exclusion"]))
    if values["deadline_required"]:
        changes["deadline_required"] = True
    if not changes and not parsed.ambiguities:
        return None, "UNSUPPORTED_REPLY"
    out, issue = apply_changes(draft, changes)
    if out:
        out["ambiguities"] = sorted(set(out["ambiguities"] + parsed.ambiguities))
        out["missing_fields"] = sorted(set(out["missing_fields"] + [f for f in parsed.missing_fields if not out.get(f)]))
        out["parse_status"] = "needs_clarification" if out["missing_fields"] or out["ambiguities"] else "ok"
    return out, issue
