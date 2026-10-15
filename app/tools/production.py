"""Bounded production-event tool validation and lifecycle delegation."""
import re
import uuid

from app.schemas.tool import ToolFailure
from app.tools.registry import validate_arguments


def execute(context, invocation_key, args):
    validate_arguments("record_production_event", args)
    words = context.user_message.casefold()
    action, order_id, reason = args["action"], args["order_id"], args["reason"]

    def named(value):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(str(value))}(?![A-Za-z0-9])", words, re.I))

    if not named(action) or not named(order_id) or reason.casefold() not in words:
        raise ToolFailure("EVENT_NOT_AUTHORIZED",
                          "The current user message must explicitly state the action, order, and audit reason.")
    if action == "complete":
        if ("workshop_id" not in args or "pieces" not in args or
                not named(args["workshop_id"]) or
                not re.search(rf"(?<!\d){args['pieces']}(?!\d)", words)):
            raise ToolFailure("EVENT_NOT_AUTHORIZED",
                              "The user must explicitly state the workshop and completed quantity.")
    elif "workshop_id" in args or "pieces" in args:
        raise ToolFailure("INVALID_ARGUMENTS", "Only completion accepts a workshop and quantity.")
    for workshop_id in [*(args.get("exclusion") or []),
                        *([args["preferred_workshop"]] if args.get("preferred_workshop") else [])]:
        if not named(workshop_id):
            raise ToolFailure("EVENT_NOT_AUTHORIZED",
                              "Each workshop constraint must be in the current user message.")
    if "objective" in args and args["objective"] != "min_delay":
        phrases = {"min_cost": ("min_cost", "minimum cost", "lowest cost", "minimize cost"),
                   "min_defects": ("min_defects", "minimum defects", "lowest defects", "minimize defects"),
                   "hybrid": ("hybrid", "balanced objective")}
        if not any(phrase in words for phrase in phrases[args["objective"]]):
            raise ToolFailure("EVENT_NOT_AUTHORIZED",
                              "The reassignment objective must be stated by the user.")
    if "max_workshops" in args and not re.search(rf"(?<!\d){args['max_workshops']}(?!\d)", words):
        raise ToolFailure("EVENT_NOT_AUTHORIZED", "The workshop limit must be stated by the user.")
    if "deadline_required" in args:
        phrase = (r"\b(?:deadline required|require deadline|meet (?:the )?deadline)\b"
                  if args["deadline_required"] else
                  r"\b(?:no deadline requirement|deadline not required)\b")
        if not re.search(phrase, words):
            raise ToolFailure("EVENT_NOT_AUTHORIZED",
                              "The deadline requirement must be stated by the user.")
    from app.services.lifecycle import process_event
    response = process_event(action, order_id, actor=context.owner, reason=reason,
        expected_version=args["expected_version"], event_id=uuid.uuid5(uuid.NAMESPACE_URL, invocation_key).hex,
        db_path=context.db_path, as_of=context.as_of, workshop_id=args.get("workshop_id"),
        pieces=args.get("pieces"), objective=args.get("objective", "min_delay"),
        exclusion=args.get("exclusion"), max_workshops=args.get("max_workshops", 1),
        preferred_workshop=args.get("preferred_workshop"), deadline_required=args.get("deadline_required", False))
    decision = response["result"]
    result = {"ok": bool(decision["success"]), "data": response}
    if not decision["success"]:
        result["error"] = {"code": decision["reason_codes"][0], "message": decision["message"]}
    return result
