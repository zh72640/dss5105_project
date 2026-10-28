"""Explain changed approval snapshots without granting permission to commit."""


def changes(previous, current, *, facts_changed=False):
    current = current or {}
    fields = (
        "allocation", "objective", "estimated_days", "estimated_delivery_date",
        "estimated_cost", "expected_defect_rate", "deadline_met", "warnings",
    )
    result = [{"field": field, "before": previous.get(field), "after": current.get(field)}
              for field in fields if previous.get(field) != current.get(field)]
    if facts_changed and not result:
        result.append({"field": "business_facts", "before": "Reviewed snapshot",
                       "after": "Updated facts; review the recalculated plan"})
    return result
