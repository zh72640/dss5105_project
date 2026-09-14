from app.schemas import AllocationResult, DecisionStatus, StructuredRequest
from app.tools.data import load_workshops
from app.tools.delivery import estimate_candidate
from app.tools.models import Order
from .scoring import with_score


def allocate(request: StructuredRequest, order: Order, objective: str = "min_lateness") -> AllocationResult:
    selected_objective = request.objective_override or objective
    metrics = [estimate_candidate(w, order.category, request.quantity or order.pieces,
        request.required_date or order.due_date, request.excluded_workshops)
        for w in load_workshops().values()]
    eligible = sorted((with_score(m, selected_objective) for m in metrics if m.eligible), key=lambda m: m.score)
    if not eligible:
        return AllocationResult(request.request_id, DecisionStatus.ESCALATE,
            candidate_ranking=metrics, reason_codes=["NO_ELIGIBLE_WORKSHOP"],
            objective=selected_objective, message="No workshop satisfies all hard constraints.")
    winner = eligible[0]
    warnings = [] if winner.deadline_met else ["ESTIMATED_DEADLINE_MISS"]
    return AllocationResult(request.request_id, DecisionStatus.ALLOCATE, winner.workshop_id,
        winner.workshop_name, eligible, ["ELIGIBLE", "BEST_CONFIGURED_SCORE"],
        selected_objective, warnings,
        f"Recommend {winner.workshop_name}: best deterministic {selected_objective} score among eligible workshops.")

