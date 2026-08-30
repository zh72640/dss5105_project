from app.schemas import AllocationResult, DecisionStatus, StructuredRequest
from app.tools.orders import resolve_order
from app.tools.workshops import get_workshop
from app.tools.eligibility import exclusion_reason


def gate_request(request: StructuredRequest) -> tuple[AllocationResult | None, object | None]:
    if any(c.type == "historical_period" for c in request.constraints):
        return AllocationResult(request.request_id, DecisionStatus.DECLINE,
            reason_codes=["DATA_NOT_AVAILABLE"],
            message="The provided data has no October workshop-allocation history, so I cannot answer reliably."), None
    order, issue = resolve_order(request)
    if issue:
        return AllocationResult(request.request_id, DecisionStatus.CLARIFY,
            reason_codes=["AMBIGUOUS_OR_MISSING_ORDER"],
            message=f"Please provide the order ID. {issue}."), None
    if request.preferred_workshop:
        workshop = get_workshop(request.preferred_workshop)
        if workshop is None:
            return AllocationResult(request.request_id, DecisionStatus.REFUSE,
                reason_codes=["UNKNOWN_WORKSHOP"], message="That workshop is not in the register."), None
        reason = exclusion_reason(workshop, order.category, request.quantity or order.pieces, request.excluded_workshops)
        if reason:
            return AllocationResult(request.request_id, DecisionStatus.REFUSE,
                reason_codes=[reason.upper()], warnings=["ALTERNATIVE_REQUIRED"],
                message=f"Cannot use {workshop.name}: {reason.replace('_', ' ')}. Please choose an eligible alternative."), None
    return None, order

