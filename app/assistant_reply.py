"""Plain-language replies grounded in the saved allocation and explicit blockers."""
OBJECTIVES = {"min_cost": "lowest total cost", "min_delay": "earliest completion",
              "min_defects": "lowest expected defect rate", "hybrid": "a balance of time and quality"}

# Each question says what is missing, why it matters, and a concrete way forward.
GUIDANCE = {
    "order_id": ("order_id", "Which order should I allocate?", "Choose an existing order below, or reply with its ID, for example ORD-045."),
    "multiple_order_ids": ("order_id", "More than one order was mentioned.", "Choose one order for this request. Start a separate request for another order."),
    "conflicting_objective": ("objective", "Should I prioritize cost, speed, or quality?", "Choose one objective below. For example, select Lowest cost."),
    "negated_objective": ("objective", "Which objective should replace the one you rejected?", "Choose an objective below."),
    "relative_due_date": ("due_date", "What is the exact due date?", "Use YYYY-MM-DD, for example 2026-04-08. It must match the registered order; this desk does not edit the order register."),
    "invalid_date": ("due_date", "The date is not valid.", "Enter a valid calendar date in the details form."),
    "conflicting_workshop_limit": ("num_workshop_allowed", "How many workshops may share this order?", "Set a single maximum, from 1 to 8, below."),
    "preferred_workshop_excluded": ("preferred_workshop", "The preferred workshop is also excluded.", "Clear the preference or remove that workshop from exclusions."),
    "UNKNOWN_EXCLUDED_WORKSHOP": ("exclusion", "An excluded workshop ID is not in the register.", "Select exclusions from the workshop list below."),
    "UNKNOWN_PREFERRED_WORKSHOP": ("preferred_workshop", "The preferred workshop is not in the register.", "Select a registered workshop or choose Any eligible workshop."),
    "unknown_workshop_name": ("preferred_workshop", "I cannot identify the workshop name.", "Select its exact name in the details form."),
    "unclear_workshop_constraint": ("preferred_workshop", "Should this workshop be used or excluded?", "Set Preferred workshop or Excluded workshops below."),
    "multiple_preferred_workshops": ("preferred_workshop", "Only one preferred workshop can be specified.", "Choose one, or clear the preference and allow multiple workshops."),
    "ORDER_NOT_FOUND": ("order_id", "That order is not in the register.", "Start a new request and select an existing order. Creating new business orders is not supported here."),
    "UNSUPPORTED_REPLY": ("details", "I could not apply this update in the current mode.", "Your previous requirements are retained. Use Edit details below, or replace the full request. Offline shortcuts include: cheapest; use two workshops; exclude W3."),
    "unsupported_constraint": ("request", "This requirement is not supported by the allocator.", "Budget caps, exact split ratios and minimum quantities are not supported. Replace the full request with supported requirements, or handle the order manually."),
    "RECOMMENDATION_REJECTED": ("details", "What would you like to change?", "Edit the objective, exclusions or workshop limit, then review the new recommendation."),
    "ORDER_SWITCH_REQUIRES_NEW_SESSION": ("order_id", "This request already belongs to another order.", "Use New request to allocate a different order."),
    "ORDER_VERSION_CONFLICT": ("details", "The order changed after your review.", "Apply your requirements again to load a fresh recommendation before approving."),
    "DEADLINE_INFEASIBLE": ("deadline_required", "No eligible plan can meet the required deadline.", "If late delivery is acceptable, turn off Hard deadline; otherwise arrange the order manually."),
    "CAPACITY_INFEASIBLE": ("num_workshop_allowed", "The allowed workshops cannot fit all remaining pieces.", "Increase Maximum workshops or review your exclusions. Batch limits still apply."),
    "NO_ELIGIBLE_WORKSHOP": ("exclusion", "No workshop meets all requirements.", "Review your exclusions and preference below, and open Calculation & eligibility details for the rejection reasons."),
    "INVALID_REQUEST": ("request", "I could not interpret this as an allocation request.", "Use an existing order and allocation requirements, for example: Allocate ORD-045 at the lowest cost. Use Production for cancellation or completion."),
}


def guidance(blockers, draft, result, trace=None, parser_error=None):
    items = []
    for code in dict.fromkeys(blockers):
        if code == "PARSER_ERROR":
            if parser_error and "api_key_missing" in parser_error:
                detail = "The server has no API key. Configure the provider environment variable locally and restart, or use Edit details without AI."
            elif parser_error and ("401" in parser_error or "403" in parser_error):
                detail = "The provider rejected the server credentials. Check the API key locally, or use Edit details without AI."
            elif parser_error and "402" in parser_error:
                detail = "The provider account has insufficient balance. Check the account locally, or use Edit details without AI."
            else:
                detail = "The model service is unavailable or returned an invalid response. Retry your text, or use Edit details without AI. No extra order information is required for this error."
            field, question = "service", "The AI service could not process this message."
        elif code.startswith("ORDER_FIELD_CONFLICT:"):
            field = code.split(":", 1)[1]
            registered = (trace or {}).get("order", {}).get(field)
            question = f"The {field.replace('_', ' ')} in your request does not match the order register."
            detail = f"Registered value: {registered}. Select Use registered order details below, or start a new request for the correct order."
        elif code.startswith("ORDER_ALREADY_"):
            field, question, detail = "order_id", "This order cannot be allocated again.", "Use Production for existing allocations, or start a new request for a Ready or Unassigned order."
        elif code == "UNKNOWN_WORKSHOP" or code.startswith(("STATUS_", "CANNOT_MAKE_", "EXCEEDS_")) or code == "EXCLUDED_BY_USER":
            field = "preferred_workshop"
            question = f"The requested workshop {draft.get('preferred_workshop') or ''} cannot take this order: {code.replace('_', ' ').lower()}."
            detail = "Choose another Preferred workshop or select Any eligible workshop. A preferred workshop must take the full remaining batch; increase the workshop limit only after clearing the preference."
        else:
            field, question, detail = GUIDANCE.get(code, (
                "request", "I still need a clarification: " + code.replace("_", " ").lower() + ".",
                "Edit the relevant field below. If this requirement cannot be expressed there, replace the full request with one clear allocation instruction."))
        items.append({"code": code, "field": field, "question": question, "help": detail})
    return items


def allocation_reply(result, order_id=None, *, committed=False):
    """The same facts produce the same reply, without an extra model call."""
    parts = result.get("allocation", [])
    if not result.get("success") or not parts:
        return result.get("message", "No allocation has been made.")
    total = sum(p["pieces"] for p in parts)
    assignments = "; ".join(f"{p['pieces']:,} pieces to {p['workshop_name']} ({p['workshop_id']})" for p in parts)
    prefix = "Approved and saved" if committed else "Proposed — awaiting your approval"
    text = f"{prefix}: {order_id or 'this order'}, {total:,} pieces. "
    text += ("I have assigned " if committed else "I recommend assigning ") + assignments + ". "
    if result.get("estimated_delivery_date"):
        text += f"Estimated completion: {result['estimated_delivery_date']}. "
    if result.get("estimated_cost") is not None:
        text += f"Estimated total cost: {result['estimated_cost']:,.2f} cost units. "
    text += "The plan targets " + OBJECTIVES.get(result.get("objective"), "your chosen objective") + "."
    if "ESTIMATED_DEADLINE_MISS" in result.get("warnings", []):
        text += " Attention: estimated completion is later than the order due date."
    if not committed:
        text += " Select Accept allocation to save it."
    return text
