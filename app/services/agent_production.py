"""Agent production-event business rules (message grounding + lifecycle)."""
import re
import uuid

from app.schemas.tool import ToolFailure


def record_production_event(
    *,
    user_message,
    owner,
    db_path,
    as_of,
    invocation_key,
    action,
    order_id,
    expected_version,
    reason,
    workshop_id=None,
    pieces=None,
    objective=None,
    exclusion=None,
    max_workshops=None,
    preferred_workshop=None,
    deadline_required=None,
):
    words = user_message.casefold()

    def named(value):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(str(value))}(?![A-Za-z0-9])", words, re.I))

    if not named(action) or not named(order_id) or reason.casefold() not in words:
        raise ToolFailure(
            "EVENT_NOT_AUTHORIZED",
            "The current user message must explicitly state the action, order, and audit reason.")
    if action == "complete":
        if (workshop_id is None or pieces is None or not named(workshop_id) or
                not re.search(rf"(?<!\d){pieces}(?!\d)", words)):
            raise ToolFailure(
                "EVENT_NOT_AUTHORIZED",
                "The user must explicitly state the workshop and completed quantity.")
    elif workshop_id is not None or pieces is not None:
        raise ToolFailure("INVALID_ARGUMENTS", "Only completion accepts a workshop and quantity.")
    for workshop in [*(exclusion or []), *([preferred_workshop] if preferred_workshop else [])]:
        if not named(workshop):
            raise ToolFailure(
                "EVENT_NOT_AUTHORIZED",
                "Each workshop constraint must be in the current user message.")
    if objective is not None and objective != "min_delay":
        phrases = {
            "min_cost": ("min_cost", "minimum cost", "lowest cost", "minimize cost"),
            "min_defects": ("min_defects", "minimum defects", "lowest defects", "minimize defects"),
            "hybrid": ("hybrid", "balanced objective"),
        }
        if not any(phrase in words for phrase in phrases[objective]):
            raise ToolFailure(
                "EVENT_NOT_AUTHORIZED",
                "The reassignment objective must be stated by the user.")
    if max_workshops is not None and not re.search(rf"(?<!\d){max_workshops}(?!\d)", words):
        raise ToolFailure("EVENT_NOT_AUTHORIZED", "The workshop limit must be stated by the user.")
    if deadline_required is not None:
        phrase = (r"\b(?:deadline required|require deadline|meet (?:the )?deadline)\b"
                  if deadline_required else
                  r"\b(?:no deadline requirement|deadline not required)\b")
        if not re.search(phrase, words):
            raise ToolFailure(
                "EVENT_NOT_AUTHORIZED",
                "The deadline requirement must be stated by the user.")

    from app.services.lifecycle import process_event
    response = process_event(
        action, order_id, actor=owner, reason=reason,
        expected_version=expected_version,
        event_id=uuid.uuid5(uuid.NAMESPACE_URL, invocation_key).hex,
        db_path=db_path, as_of=as_of,
        workshop_id=workshop_id, pieces=pieces,
        objective=objective if objective is not None else "min_delay",
        exclusion=exclusion,
        max_workshops=max_workshops if max_workshops is not None else 1,
        preferred_workshop=preferred_workshop,
        deadline_required=bool(deadline_required) if deadline_required is not None else False)
    decision = response["result"]
    result = {"ok": bool(decision["success"]), "data": response}
    if not decision["success"]:
        result["error"] = {"code": decision["reason_codes"][0], "message": decision["message"]}
    return result
