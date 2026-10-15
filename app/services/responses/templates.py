"""Fixed user-facing copy. These strings are never sent as LLM instructions."""
OBJECTIVES = {"min_cost": "lowest total cost", "min_delay": "earliest completion",
              "min_defects": "lowest expected defect rate", "hybrid": "a balance of time and quality"}

SERVICE_ERRORS = {
    "missing_key": "The server has no API key. Configure the provider environment variable locally and restart, or use Edit details without AI.",
    "credentials": "The provider rejected the server credentials. Check the API key locally, or use Edit details without AI.",
    "balance": "The provider account has insufficient balance. Check the account locally, or use Edit details without AI.",
    "unavailable": "The model service is unavailable or returned an invalid response. Retry your text, or use Edit details without AI. No extra order information is required for this error.",
}

TEXT = {
    "edit_details": "Edit details: ",
    "save_failed": "Save failed and the transaction was rolled back. Retry with the same request ID.",
    "draft_updated": "Draft updated. Review the recommendation and accept to allocate.",
    "service_question": "The AI service could not process this message.",
    "field_conflict_question": "The {field} in your request does not match the order register.",
    "field_conflict_help": "Registered value: {value}. Select Use registered order details below, or start a new request for the correct order.",
    "already_allocated_question": "This order cannot be allocated again.",
    "already_allocated_help": "Use Production for existing allocations, or start a new request for a Ready or Unassigned order.",
    "workshop_question": "The requested workshop {workshop} cannot take this order: {reason}.",
    "workshop_help": "Choose another Preferred workshop or select Any eligible workshop. A preferred workshop must take the full remaining batch; increase the workshop limit only after clearing the preference.",
    "fallback_question": "I still need a clarification: {reason}.",
    "fallback_help": "Edit the relevant field below. If this requirement cannot be expressed there, replace the full request with one clear allocation instruction.",
    "no_allocation": "No allocation has been made.",
    "assignment": "{pieces:,} pieces to {workshop_name} ({workshop_id})",
    "approved": "Approved and saved",
    "proposed": "Proposed — awaiting your approval",
    "this_order": "this order",
    "allocation_intro": "{prefix}: {order}, {total:,} pieces. ",
    "assigned": "I have assigned ",
    "recommend": "I recommend assigning ",
    "completion": "Estimated completion: {date}. ",
    "cost": "Estimated total cost: {cost:,.2f} cost units. ",
    "objective": "The plan targets {objective}.",
    "chosen_objective": "your chosen objective",
    "lateness": " Attention: estimated completion is later than the order due date.",
    "accept": " Select Accept allocation to save it.",
}

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


REPLY_HELP = (
    "Provide an order ID, or use: use two workshops, exclude W3, clear exclusions, cheapest, "
    "fastest, lowest defects. For complex changes use Replace full request. "
    "Review the recommendation before accepting.")
