"""Fixed user-facing copy. These strings are never sent as LLM instructions."""
OBJECTIVES = {"min_cost": "lowest total cost", "min_delay": "earliest completion",
              "min_defects": "lowest expected defect rate", "hybrid": "a balance of time and quality", "weighted_hybrid": "normalized 80/20 lateness and defect exposure"}


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


REPLY_HELP = (
    "Provide an order ID, or use: use two workshops, exclude W3, clear exclusions, cheapest, "
    "fastest, lowest defects. For complex changes use Replace full request. "
    "Review the recommendation before accepting.")
