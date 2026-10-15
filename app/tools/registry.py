"""Registered native tool contracts and task permissions."""
from app.schemas.tool import ToolFailure

def schema(name, description, properties, required=()):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(required), "additionalProperties": False}}}


STRING = {"type": "string"}
TOOLS = {
    "get_order": schema("get_order", "Read a registered order, current state, version, and remaining pieces. Returns data or ORDER_NOT_FOUND.",
                        {"order_id": STRING}, ("order_id",)),
    "list_workshops": schema("list_workshops", "Read current workshops and aged queue values for the business date. Optional workshop_id filters one resource.",
                             {"workshop_id": STRING}),
    "get_queue": schema("get_queue", "Read one workshop's current aged queue in days.",
                        {"workshop_id": STRING}, ("workshop_id",)),
    "score_workshop": schema("score_workshop", "Call all four restored single-workshop allocation.py functions. Uses business date as sent_date; this is not the current planner's weighted hybrid objective.",
                             {"workshop_id": STRING, "order_id": STRING, "pieces": {"type": "integer", "minimum": 1}},
                             ("workshop_id", "order_id")),
    "update_constraints": schema("update_constraints", "Apply one requirement grounded in the current user message. Supersedes an old recommendation. Returns validation errors for invented or invalid values.",
                                 {"field": STRING, "value": {}, "operation": {"type": "string", "enum": ["set", "unset", "add", "remove", "undo"]}},
                                 ("field",)),
    "check_requirements": schema("check_requirements", "Run authoritative preflight and move task to READY only when complete and conflict-free.", {}, ()),
    "compute_plan": schema("compute_plan", "Compute and verify an integer allocation plan for a READY task. Does not save a recommendation or production allocation.", {}, ()),
    "save_recommendation": schema("save_recommendation", "Save the plan computed in this run after checking fresh facts and the plan hash. Does not write production allocations.", {}, ()),
    "inspect_recommendation": schema("inspect_recommendation", "Read the saved recommendation and current validity from the database.", {}, ()),
    "ask_user": schema("ask_user", "Pause this turn with a concrete question. The next user message resumes the same session and Skill snapshot.",
                       {"question": STRING}, ("question",)),
    "record_production_event": schema("record_production_event", "Record an explicitly requested, audited production event through the existing lifecycle service. The authenticated account is the actor and the server generates an idempotent event ID. Returns the saved result or refusal.",
        {"action": {"type": "string", "enum": ["complete", "cancel", "lapse", "reassign"]},
         "order_id": STRING, "expected_version": {"type": "integer", "minimum": 0},
         "reason": STRING, "workshop_id": STRING, "pieces": {"type": "integer", "minimum": 1},
         "objective": {"type": "string", "enum": ["min_delay", "min_cost", "min_defects", "hybrid"]},
         "exclusion": {"type": "array", "items": STRING},
         "max_workshops": {"type": "integer", "minimum": 1}, "preferred_workshop": STRING,
         "deadline_required": {"type": "boolean"}},
        ("action", "order_id", "expected_version", "reason")),
}

from app.services.agent_operations import ALLOWED_TASK_STATES


def validate_arguments(name, arguments):
    if name not in TOOLS or not isinstance(arguments, dict):
        raise ToolFailure("UNKNOWN_TOOL", "The requested tool is not registered.")
    spec = TOOLS[name]["function"]["parameters"]
    if set(arguments) - set(spec["properties"]) or set(spec["required"]) - set(arguments):
        raise ToolFailure("INVALID_ARGUMENTS", "Tool arguments do not match the declared schema.")
    for key, value in arguments.items():
        rule = spec["properties"][key]
        kind = rule.get("type")
        if kind == "string" and (not isinstance(value, str) or not value.strip()):
            raise ToolFailure("INVALID_ARGUMENTS", f"{key} must be a nonempty string.")
        if kind == "integer" and (type(value) is not int or value < rule.get("minimum", 0)):
            raise ToolFailure("INVALID_ARGUMENTS", f"{key} must be a positive integer.")
        if kind == "boolean" and type(value) is not bool:
            raise ToolFailure("INVALID_ARGUMENTS", f"{key} must be a boolean.")
        if kind == "array" and (not isinstance(value, list) or
                any(not isinstance(item, str) for item in value)):
            raise ToolFailure("INVALID_ARGUMENTS", f"{key} must be a string list.")
        if "enum" in rule and value not in rule["enum"]:
            raise ToolFailure("INVALID_ARGUMENTS", f"{key} is unsupported.")



ALLOCATION_TOOLS = frozenset({
    "get_order", "list_workshops", "get_queue", "score_workshop",
    "update_constraints", "check_requirements", "compute_plan",
    "save_recommendation", "inspect_recommendation", "ask_user",
})


def allowed_for_task(name: str, task_type: str) -> bool:
    """Code-owned authorization independent of Skill text."""
    return name in TOOLS and (task_type != "allocation" or name in ALLOCATION_TOOLS)
