"""Pure validation rules for production events, shared by all application entrypoints."""
from datetime import date
from app.schemas.parser_schema import OBJECTIVES

ACTIONS = ("complete", "cancel", "lapse", "reassign")


def valid_text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def check_arguments(action, order_id, actor, reason, expected_version, event_id, as_of,
                    workshop_id, pieces, objective, exclusion, max_workshops, preferred_workshop, deadline_required):
    if not all((valid_text(order_id, 128), valid_text(actor, 120), valid_text(reason, 2000),
                valid_text(event_id, 128), type(expected_version) is int and expected_version >= 0,
                type(as_of) is date, isinstance(action, str) and action in ACTIONS)):
        return False
    if action == "complete":
        if not valid_text(workshop_id, 128) or type(pieces) is not int or pieces <= 0:
            return False
    elif workshop_id is not None or pieces is not None:
        return False
    if action != "reassign":
        return (objective == "min_delay" and exclusion is None and max_workshops == 1 and
                preferred_workshop is None and deadline_required is False)
    return (isinstance(objective, str) and objective in OBJECTIVES and
            (exclusion is None or isinstance(exclusion, list) and len(exclusion) <= 100 and
             all(valid_text(item, 128) for item in exclusion)) and
            type(max_workshops) is int and 1 <= max_workshops <= 8 and
            (preferred_workshop is None or valid_text(preferred_workshop, 128)) and
            type(deadline_required) is bool)


def allowed_states(action):
    return ("READY", "UNASSIGNED", "WORKING") if action == "lapse" else ("WORKING",)
