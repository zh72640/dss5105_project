"""Deterministic integer splits over <=8 workshops. No LLM decisions."""
import math
from heapq import merge
from datetime import date, timedelta
from itertools import combinations, groupby

from app.allocator.eligibility import exclusion_reason
from app.allocator.strategies import normalize_weighted, explanation_evidence


def _part(workshop, quantity):
    return {"workshop_id": workshop.workshop_id, "workshop_name": workshop.name,
            "pieces": quantity, "queue_days": workshop.queue_days,
            "processing_days": quantity / workshop.capacity,
            "transport_days": workshop.lead_days,
            "estimated_days": workshop.queue_days + quantity / workshop.capacity + workshop.lead_days,
            "estimated_cost": round(quantity * workshop.cost, 2), "defect_rate": workshop.defect_rate}


def _hybrid_split(subset, pieces, caps):
    """Optimize the weighted objective at every attainable integer finish time.

    At a fixed finish time, defect exposure is a linear unit cost and is minimized
    by filling the lowest-defect available capacity first. Every optimal plan's
    makespan is a completion breakpoint of one of its used workshops. Enumerating
    those breakpoints therefore optimizes the weighted objective for this subset;
    it does not optimize a schedule of future orders.
    """
    ranked = sorted(subset, key=lambda w: (w.defect_rate, w.cost, w.workshop_id))

    def events(workshop):
        for quantity in range(1, caps[workshop.workshop_id] + 1):
            yield (workshop.queue_days + workshop.lead_days + quantity / workshop.capacity,
                   workshop.workshop_id, quantity)

    available = {w.workshop_id: 0 for w in subset}
    total, best_key, best_parts, previous = 0, None, None, None
    for _, simultaneous in groupby(merge(*(events(w) for w in subset)), key=lambda item: item[0]):
        for _, wid, quantity in simultaneous:
            total += quantity - available[wid]
            available[wid] = quantity
        if total < pieces:
            continue
        remaining, quantities = pieces, []
        for workshop in ranked:
            quantity = min(remaining, available[workshop.workshop_id])
            quantities.append(quantity)
            remaining -= quantity
        if quantities == previous:
            continue
        previous = quantities
        used = [(w, q) for w, q in zip(ranked, quantities) if q]
        days = max(w.queue_days + w.lead_days + q / w.capacity for w, q in used)
        defects = sum(q * w.defect_rate for w, q in used) / pieces
        cost = round(sum(round(q * w.cost, 2) for w, q in used), 2)
        key = (round(.6 * days + .4 * defects * 100, 10), days, cost,
               len(used), [w.workshop_id for w, _ in used])
        if best_key is None or key < best_key:
            best_key = key
            best_parts = [_part(w, q) for w, q in used]
    return best_parts


def _split(subset, pieces, objective, day_limit=None):
    caps = {w.workshop_id: min(pieces, w.max_batch or pieces) for w in subset}
    if day_limit is not None:
        caps = {w.workshop_id: min(caps[w.workshop_id], max(0, math.floor(
            (day_limit - w.queue_days - w.lead_days) * w.capacity + 1e-8))) for w in subset}
    if sum(caps.values()) < pieces:
        return None
    if objective == "hybrid" and len(subset) > 1:
        return _hybrid_split(subset, pieces, caps)
    if objective == "min_delay":
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
            parts.append(_part(w, quantity))
            remaining -= quantity
        if not remaining:
            break
    return parts if remaining == 0 else None


def plan(order, workshops, *, objective, as_of, max_workshops=1, exclusion=None,
         preferred_workshop=None, deadline_required=False):
    """Enumerate 1..max_workshops configurations. max_workshops>=2 enables splits."""
    pieces = order["pieces"]
    requested_limit = max_workshops
    exclusion = list(exclusion or [])
    max_workshops = min(max_workshops, len(workshops))
    rejected, eligible = {}, []
    for w in workshops:
        # For splits, batch caps constrain each part, not the full order.
        reason = exclusion_reason(w, order["category"], pieces if max_workshops == 1 else 1, exclusion)
        if w.capacity <= 0 or w.queue_days < 0:
            reason = "invalid_capacity_or_queue"
        if reason:
            rejected[w.workshop_id] = reason
        else:
            eligible.append(w)
    base = {"success": False, "decision_status": "ESCALATE", "allocation": [],
            "objective": objective, "rejected": rejected, "reason_codes": [], "warnings": [],
            "eligible_workshops": [w.workshop_id for w in eligible], "candidate_ranking": [],
            "candidate_plans": [], "candidate_plan_count": 0}
    if objective == "weighted_hybrid" and requested_limit > 1:
        return {**base, "reason_codes": ["WEIGHTED_HYBRID_SINGLE_WORKSHOP_ONLY"],
                "message": "Normalized 80/20 scoring supports one workshop. Use a one-workshop limit or choose another objective for splitting."}
    if preferred_workshop:
        preferred = next((w for w in workshops if w.workshop_id == preferred_workshop), None)
        reason = "unknown_workshop" if preferred is None else exclusion_reason(
            preferred, order["category"], pieces, exclusion)
        if reason:
            return {**base, "decision_status": "REFUSE", "reason_codes": [reason.upper()],
                    "message": "Requested workshop cannot take the full batch; submit a new request with an eligible alternative."}
        eligible = [preferred]
        max_workshops = 1
    if not eligible:
        return {**base, "reason_codes": ["NO_ELIGIBLE_WORKSHOP"], "message": "No workshop satisfies eligibility rules."}
    deadline = date.fromisoformat(order["due_date"])
    day_limit = (deadline - as_of).days if deadline_required else None
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
                     "hybrid": .6 * days + .4 * defects * 100, "weighted_hybrid": 0.0}[objective]
            options.append({"allocation": parts, "estimated_days": days, "estimated_cost": cost,
                            "expected_defect_rate": defects, "score": score})
    if not options:
        reason = "DEADLINE_INFEASIBLE" if deadline_required else "CAPACITY_INFEASIBLE"
        return {**base, "reason_codes": [reason], "message": "No complete integer allocation satisfies the batch/count/deadline constraints."}
    if objective == "weighted_hybrid":
        normalize_weighted(options, (deadline - as_of).days)
    options.sort(key=lambda p: (round(p["score"], 10), p["estimated_days"], p["estimated_cost"],
                               len(p["allocation"]), [a["workshop_id"] for a in p["allocation"]]))
    best = options[0]
    # Conservative whole-day display; shared official simulator uses round(), left unchanged.
    delivery = as_of + timedelta(days=math.ceil(best["estimated_days"] - 1e-10))
    warnings = [] if delivery <= deadline else ["ESTIMATED_DEADLINE_MISS"]
    ranking = [{"workshop_id": p["allocation"][0]["workshop_id"],
                "workshop_name": p["allocation"][0]["workshop_name"], **p}
               for p in options if len(p["allocation"]) == 1]
    seen, candidates = set(), []
    for option in options:
        identity = tuple(sorted((p["workshop_id"], p["pieces"]) for p in option["allocation"]))
        if identity in seen:
            continue
        seen.add(identity)
        if len(candidates) < 5:
            eta = as_of + timedelta(days=math.ceil(option["estimated_days"] - 1e-10))
            candidates.append({**option, "objective": objective,
                               "estimated_delivery_date": eta.isoformat(), "deadline_met": eta <= deadline,
                               "warnings": [] if eta <= deadline else ["ESTIMATED_DEADLINE_MISS"],
                               "constraints": {"max_workshops": max_workshops,
                                               "exclusion": exclusion,
                                               "required_sole_workshop": preferred_workshop,
                                               "deadline_required": deadline_required}})
    return {**base, **best, "success": True, "decision_status": "ALLOCATE",
            "recommended_workshop_id": best["allocation"][0]["workshop_id"],
            "recommended_workshop_name": ", ".join(p["workshop_name"] for p in best["allocation"]),
            "estimated_delivery_date": delivery.isoformat(), "deadline_met": delivery <= deadline,
            "candidate_ranking": ranking, "warnings": warnings,
            "candidate_plans": candidates, "candidate_plan_count": len(seen),
            "candidate_plan_scope": "Up to five distinct best plans from the evaluated workshop subsets.",
            "explanation_evidence": explanation_evidence(best, options, objective, rejected,
                [w.workshop_id for w in eligible], preferred_workshop, deadline_required),
            "reason_codes": ["ELIGIBLE", "BEST_CONFIGURED_SCORE", "INTEGER_PIECES_CONSERVED"],
            "message": f"Allocated {pieces} pieces to {len(best['allocation'])} workshop(s) using {objective}."}
