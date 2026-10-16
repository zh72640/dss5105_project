"""Deterministic input checks and result projection; no database access."""
from datetime import date

from pydantic import ValidationError

from app.schemas.allocation import AllocationFields, AllocationSkillInput, AllocationRecommendationResult
from app.services.allocation.preflight import issue

FIELDS = tuple(AllocationFields.model_fields)


def inspect_input(value, *, skill=False):
    """Return a complete four-field input or explicit missing/invalid issues."""
    if not isinstance(value, dict):
        return None, [issue("INVALID_ALLOCATION_INPUT", "workflow",
                            "Allocation input must contain the four required fields.")]
    data = {field: value.get(field) for field in FIELDS}
    missing = [field for field, item in data.items()
               if item is None or isinstance(item, str) and not item.strip()]
    if missing:
        code = "SKILL_INPUT_INCOMPLETE" if skill else "REQUIRED_INFO_INCOMPLETE"
        prefix = "Missing required field(s): " if skill else "Required information is incomplete: "
        return None, [{**issue(code, field, prefix + ", ".join(missing) + "."),
                       "missing_fields": missing} for field in missing]
    try:
        return AllocationSkillInput.model_validate(data).model_dump(), []
    except ValidationError as error:
        invalid = sorted({str(item["loc"][0]) for item in error.errors()})
        return None, [issue("INVALID_ALLOCATION_INPUT", field,
                            "Allocation field validation failed: " + ", ".join(invalid) + ".")
                      for field in invalid]


def single_workshop_issues(draft):
    limit = draft.get("num_workshop_allowed")
    if type(limit) is int and limit > 1:
        return [issue("MULTI_WORKSHOP_UNSUPPORTED", "num_workshop_allowed",
                      "This allocation workflow supports one workshop only.")]
    return []


def add_order_snapshot(order, result):
    """Preserve the facts used for this plan alongside the existing planner result."""
    if not result.get("success"):
        return result
    return {**result, "order_id": order["order_id"], "product": order["product"],
            "pieces": order["pieces"], "due_date": order["due_date"],
            "allocated_pieces": sum(part["pieces"] for part in result["allocation"]),
            "delay_days": (date.fromisoformat(result["estimated_delivery_date"]) -
                           date.fromisoformat(order["due_date"])).days}


def saved_result(recommendation):
    """Project a saved single-workshop recommendation, never current mutable facts."""
    result = recommendation["result"]
    parts = result.get("allocation", [])
    if len(parts) != 1:
        raise ValueError("A single-workshop recommendation is required.")
    part = parts[0]
    payload = {key: result[key] for key in (*FIELDS, "allocated_pieces", "delay_days",
               "estimated_delivery_date", "expected_defect_rate", "estimated_cost", "objective", "warnings")}
    payload.update(recommendation_id=recommendation["recommendation_id"],
                   task_version=recommendation["task_version"],
                   workshop_id=part["workshop_id"], workshop_name=part["workshop_name"])
    validated = AllocationRecommendationResult.model_validate(payload)
    if (validated.allocated_pieces != part["pieces"] or
            validated.allocated_pieces > validated.pieces or
            abs(validated.expected_defect_rate - part["defect_rate"]) > 1e-10 or
            validated.estimated_cost != part["estimated_cost"] or validated.delay_days != (
            date.fromisoformat(validated.estimated_delivery_date) - date.fromisoformat(validated.due_date)).days):
        raise ValueError("The saved recommendation summary is inconsistent.")
    return validated.model_dump()
