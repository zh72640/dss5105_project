"""Deterministic integer splits over <=8 workshops. No LLM decisions."""
import math
from datetime import date, timedelta
from itertools import combinations
from app.tools.eligibility import exclusion_reason


def _split(subset, pieces, objective, day_limit=None):
    caps = {w.workshop_id: min(pieces, w.max_batch or pieces) for w in subset}
    if day_limit is not None:
        caps = {w.workshop_id: min(caps[w.workshop_id], max(0, math.floor(
            (day_limit - w.queue_days - w.lead_days) * w.capacity + 1e-8))) for w in subset}
    if sum(caps.values()) < pieces:
        return None
    if objective in ("min_delay", "hybrid"):
        # Integer minimax: binary search the earliest time with enough pieces of capacity.
        low = 0.
        high = max(w.queue_days + w.lead_days + caps[w.workshop_id] / w.capacity for w in subset)
        for _ in range(64):
            mid = (low + high) / 2
            possible = sum(min(caps[w.workshop_id], max(0, math.floor((mid-w.queue_days-w.lead_days)*w.capacity + 1e-8))) for w in subset)
            if possible >= pieces:
                high = mid
            else:
                low = mid
        caps = {w.workshop_id: min(caps[w.workshop_id], max(0, math.floor(
            (high - w.queue_days - w.lead_days) * w.capacity + 1e-7))) for w in subset}
    key = (lambda w: (w.defect_rate, w.cost, w.workshop_id)) if objective == "min_defects" else (lambda w: (w.cost, w.defect_rate, w.workshop_id))
    remaining, parts = pieces, []
    for w in sorted(subset, key=key):
        quantity = min(remaining, caps[w.workshop_id])
        if quantity:
            parts.append({"workshop_id": w.workshop_id, "workshop_name": w.name, "pieces": quantity,
                          "queue_days": w.queue_days, "processing_days": quantity / w.capacity,
                          "transport_days": w.lead_days,
                          "estimated_days": w.queue_days + quantity / w.capacity + w.lead_days,
                          "estimated_cost": round(quantity * w.cost, 2), "defect_rate": w.defect_rate})
            remaining -= quantity
        if not remaining:
            break
    return parts if remaining == 0 else None


def plan(order, workshops, parsed, objective, as_of):
    pieces = order["pieces"]
    max_workshops = min(parsed.num_workshop_allowed or 1, len(workshops))
    rejected, eligible = {}, []
    for w in workshops:
        # For splits, batch caps constrain each part, not the full order.
        reason = exclusion_reason(w, order["category"], pieces if max_workshops == 1 else 1, parsed.exclusion)
        if w.capacity <= 0 or w.queue_days < 0:
            reason = "invalid_capacity_or_queue"
        if reason:
            rejected[w.workshop_id] = reason
        else:
            eligible.append(w)
    base = {"success": False, "decision_status": "ESCALATE", "allocation": [],
            "objective": objective, "rejected": rejected, "reason_codes": [], "warnings": [],
            "eligible_workshops": [w.workshop_id for w in eligible], "candidate_ranking": []}
    if parsed.preferred_workshop:
        preferred = next((w for w in workshops if w.workshop_id == parsed.preferred_workshop), None)
        reason = "unknown_workshop" if preferred is None else exclusion_reason(preferred, order["category"], pieces, parsed.exclusion)
        if reason:
            return {**base, "decision_status": "REFUSE", "reason_codes": [reason.upper()],
                    "message": "Requested workshop cannot take the full batch; submit a new request with an eligible alternative."}
        eligible = [preferred]
        max_workshops = 1
    if not eligible:
        return {**base, "reason_codes": ["NO_ELIGIBLE_WORKSHOP"], "message": "No workshop satisfies eligibility rules."}
    deadline = date.fromisoformat(order["due_date"])
    day_limit = (deadline - as_of).days if parsed.deadline_required else None
    options = []
    for count in range(1, min(max_workshops, len(eligible)) + 1):
        for subset in combinations(eligible, count):
            parts = _split(subset, pieces, objective, day_limit)
            if not parts:
                continue
            days = max(p["estimated_days"] for p in parts)
            cost = round(sum(p["estimated_cost"] for p in parts), 2)
            defects = sum(p["pieces"] * p["defect_rate"] for p in parts) / pieces
            score = {"min_delay": days, "min_cost": cost, "min_defects": defects,
                     "hybrid": .6 * days + .4 * defects * 100}[objective]
            options.append({"allocation": parts, "estimated_days": days, "estimated_cost": cost,
                            "expected_defect_rate": defects, "score": score})
    if not options:
        reason = "DEADLINE_INFEASIBLE" if parsed.deadline_required else "CAPACITY_INFEASIBLE"
        return {**base, "reason_codes": [reason], "message": "No complete integer allocation satisfies the batch/count/deadline constraints."}
    options.sort(key=lambda p: (round(p["score"], 10), p["estimated_days"], p["estimated_cost"],
                               len(p["allocation"]), [a["workshop_id"] for a in p["allocation"]]))
    best = options[0]
    # Conservative whole-day display; shared official simulator uses round(), left unchanged.
    delivery = as_of + timedelta(days=math.ceil(best["estimated_days"] - 1e-10))
    warnings = [] if delivery <= deadline else ["ESTIMATED_DEADLINE_MISS"]
    ranking = [{"workshop_id": p["allocation"][0]["workshop_id"],
                "workshop_name": p["allocation"][0]["workshop_name"], **p}
               for p in options if len(p["allocation"]) == 1]
    return {**base, **best, "success": True, "decision_status": "ALLOCATE",
            "recommended_workshop_id": best["allocation"][0]["workshop_id"],
            "recommended_workshop_name": ", ".join(p["workshop_name"] for p in best["allocation"]),
            "estimated_delivery_date": delivery.isoformat(), "deadline_met": delivery <= deadline,
            "candidate_ranking": ranking, "warnings": warnings,
            "reason_codes": ["ELIGIBLE", "BEST_CONFIGURED_SCORE", "INTEGER_PIECES_CONSERVED"],
            "message": f"Allocated {pieces} pieces to {len(best['allocation'])} workshop(s) using {objective}."}
