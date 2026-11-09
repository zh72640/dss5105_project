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
    """Score candidates; unknown dates use normalized completion time.

    Subtracting the same allowed-days constant leaves min-max scores unchanged.
    Keep completion evidence explicit rather than inventing a lateness baseline.
    """
    lateness = [p["estimated_days"] - allowed_days if allowed_days is not None else p['estimated_days'] for p in options]
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
        if allowed_days is None:
            components = plan['scoring_components']
            for old, new in (('signed_lateness_days', 'completion_days'),
                             ('normalized_lateness', 'normalized_completion'),
                             ('lateness_weight', 'completion_weight')):
                components[new] = components.pop(old)


def explanation_evidence(best, options, objective, rejected, eligible, preferred, deadline_required, *, due_date_known=True):
    """Snapshot the facts behind a single-workshop choice for later explanation."""
    if len(best["allocation"]) != 1:
        return None
    part = best["allocation"][0]
    method, formula = METHODS[objective]
    if not due_date_known:
        if objective == 'min_delay':
            formula = 'Minimize completion days; no due date is available for lateness assessment.'
        elif objective == 'weighted_hybrid':
            method = 'Normalized completion time and defect exposure (80/20)'
            formula = formula.replace('signed lateness', 'completion days')
    return {
        "method": method, "score_formula": formula,
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
