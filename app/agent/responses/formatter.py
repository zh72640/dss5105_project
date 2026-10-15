"""Format saved business facts and explicit blockers into deterministic user replies."""
from .templates import GUIDANCE, OBJECTIVES, SERVICE_ERRORS, TEXT


def guidance(blockers, draft, result, trace=None, parser_error=None):
    items = []
    for code in dict.fromkeys(blockers):
        if code == "PARSER_ERROR":
            if parser_error and "api_key_missing" in parser_error:
                detail = SERVICE_ERRORS["missing_key"]
            elif parser_error and ("401" in parser_error or "403" in parser_error):
                detail = SERVICE_ERRORS["credentials"]
            elif parser_error and "402" in parser_error:
                detail = SERVICE_ERRORS["balance"]
            else:
                detail = SERVICE_ERRORS["unavailable"]
            field, question = "service", TEXT["service_question"]
        elif code.startswith("ORDER_FIELD_CONFLICT:"):
            field = code.split(":", 1)[1]
            registered = (trace or {}).get("order", {}).get(field)
            question = TEXT["field_conflict_question"].format(field=field.replace("_", " "))
            detail = TEXT["field_conflict_help"].format(value=registered)
        elif code.startswith("ORDER_ALREADY_"):
            field, question, detail = "order_id", TEXT["already_allocated_question"], TEXT["already_allocated_help"]
        elif code == "UNKNOWN_WORKSHOP" or code.startswith(("STATUS_", "CANNOT_MAKE_", "EXCEEDS_")) or code == "EXCLUDED_BY_USER":
            field = "preferred_workshop"
            question = TEXT["workshop_question"].format(workshop=draft.get("preferred_workshop") or "",
                                                       reason=code.replace("_", " ").lower())
            detail = TEXT["workshop_help"]
        else:
            field, question, detail = GUIDANCE.get(code, (
                "request", TEXT["fallback_question"].format(reason=code.replace("_", " ").lower()),
                TEXT["fallback_help"]))
        items.append({"code": code, "field": field, "question": question, "help": detail})
    return items


def allocation_reply(result, order_id=None, *, committed=False):
    parts = result.get("allocation", [])
    if not result.get("success") or not parts:
        return result.get("message", TEXT["no_allocation"])
    total = sum(part["pieces"] for part in parts)
    assignments = "; ".join(TEXT["assignment"].format(**part) for part in parts)
    prefix = TEXT["approved"] if committed else TEXT["proposed"]
    text = TEXT["allocation_intro"].format(prefix=prefix, order=order_id or TEXT["this_order"], total=total)
    text += (TEXT["assigned"] if committed else TEXT["recommend"]) + assignments + ". "
    if result.get("estimated_delivery_date"):
        text += TEXT["completion"].format(date=result["estimated_delivery_date"])
    if result.get("estimated_cost") is not None:
        text += TEXT["cost"].format(cost=result["estimated_cost"])
    text += TEXT["objective"].format(objective=OBJECTIVES.get(result.get("objective"), TEXT["chosen_objective"]))
    if "ESTIMATED_DEADLINE_MISS" in result.get("warnings", []):
        text += TEXT["lateness"]
    if not committed:
        text += TEXT["accept"]
    return text
