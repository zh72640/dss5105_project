"""Pure scoring and evidence for the normalized policy from zhen/0ffc0b8."""

METHODS = {
    "min_delay": ("Earliest completion", "Minimize completion days (equivalently signed lateness for this order)."),
    "min_cost": ("Lowest production cost", "Minimize total allocated quantity times registered unit cost."),
    "min_defects": ("Lowest expected defect rate", "Minimize the quantity-weighted expected defect rate."),
    "hybrid": ("Time and quality balance", "Minimize 0.6 * completion days + 0.4 * expected defect percentage."),
    "weighted_hybrid": ("Normalized lateness and defect exposure (80/20)",
                        "Minimize 0.8 * normalized signed lateness + 0.2 * normalized defect exposure. "
                        "Defect exposure = defect rate * pieces / daily capacity. "
                        "Each component uses min-max scaling across feasible candidates; a constant range contributes zero."),
}


def normalize_weighted(options, allowed_days):
    """Score complete single-workshop candidates in-place; no eligibility or writes."""
    lateness = [p["estimated_days"] - allowed_days for p in options]
    exposure = [p["allocation"][0]["defect_rate"] * p["allocation"][0]["processing_days"] for p in options]

    def scale(values):
        low, high = min(values), max(values)
        return [0.0 if high == low else (value - low) / (high - low) for value in values]

    for plan, late, defect, norm_late, norm_defect in zip(options, lateness, exposure, scale(lateness), scale(exposure)):
        plan["score"] = .8 * norm_late + .2 * norm_defect
        plan["scoring_components"] = {
            "signed_lateness_days": late, "defect_exposure": defect,
            "normalized_lateness": norm_late, "normalized_defect_exposure": norm_defect,
            "lateness_weight": .8, "defect_weight": .2,
        }


def explanation_evidence(best, options, objective, rejected, eligible, preferred, deadline_required):
    """Snapshot the facts behind a single-workshop choice for later explanation."""
    if len(best["allocation"]) != 1:
        return None
    part = best["allocation"][0]
    return {
        "method": METHODS[objective][0], "score_formula": METHODS[objective][1],
        "comparison_scope": "Feasible single-workshop plans under the saved request constraints.",
        "selection_reason": ("Required sole workshop specified by the user." if preferred else
                             "Lowest configured score; ties use completion time, cost, then workshop ID."),
        "selected_score": best["score"], "queue_days": part["queue_days"],
        "processing_days": part["processing_days"], "transport_days": part["transport_days"],
        "eligible_workshops": list(eligible), "rejected_workshops": dict(rejected),
        "required_sole_workshop": preferred, "deadline_required": deadline_required,
        "candidates": [{"workshop_id": p["allocation"][0]["workshop_id"],
                        "workshop_name": p["allocation"][0]["workshop_name"],
                        "score": p["score"], "estimated_days": p["estimated_days"],
                        "estimated_cost": p["estimated_cost"], "expected_defect_rate": p["expected_defect_rate"],
                        "scoring_components": p.get("scoring_components", {})}
                       for p in options if len(p["allocation"]) == 1],
    }
