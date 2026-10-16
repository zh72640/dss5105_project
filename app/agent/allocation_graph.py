"""Allocation-specific fixed preparation, Skill loading and guarded tool execution."""
from typing import TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent import skills
from app.services.conversation_context import build_context
from app.services.interpretation import validate_interpretation
from app.agent.dynamic import AgentContext, final_text, record_model_response
from app.llm.errors import check_response, check_structured, text_content, translate_error
from app.agent.executor import run as run_executor, waiting_skill_snapshots
from app.db.database import Database
from app.db.chat_repository import snapshot
from app.prompts import get_registry
from app.schemas.chat import TurnInterpretation
from app.services import allocation_preparation
from app.tools.registry import TOOLS, allowed_for_task


class AllocationState(TypedDict, total=False):
    messages: list
    interpretation: dict
    sequence: int
    preparation: dict
    loaded_skills: dict
    task_result: dict
    reply: str
    tool_results: list
    pending_question: str | None


def _failed(code, message, task_id=""):
    return {"task_id": task_id, "task_type": "allocation", "status": "failed",
            "result": None, "issues": [{"code": code, "field": "workflow",
                                         "severity": "blocking", "question": message}]}


def extract_fields(state: AllocationState, runtime: Runtime[AgentContext]):
    context = runtime.context
    with Database(context.db_path) as db:
        session = snapshot(db.connection, context.session_id, context.owner)
        if session is None:
            return {"task_result": _failed("SESSION_NOT_FOUND", "The session is unavailable.")}
        conversation = build_context(db.connection, session)
    bundle = get_registry().render("allocation.extract",
        variables={"context": conversation,
                   "output_schema": TurnInterpretation.model_json_schema()},
        user_message=context.user_message)
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    try:
        if spec.output_method == "prompt":
            raw = model.invoke(bundle.as_messages())
        else:
            result = model.with_structured_output(TurnInterpretation, method=spec.output_method,
                include_raw=True).invoke(bundle.as_messages())
            raw = result.get("raw") if isinstance(result, dict) else None
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    if raw is not None:
        record_model_response(context, "extract", raw, bundle.metadata)
    try:
        interpretation = (TurnInterpretation.model_validate_json(text_content(check_response(raw)))
            if spec.output_method == "prompt" else TurnInterpretation.model_validate(check_structured(result)[0]))
        validate_interpretation(interpretation, context.user_message, conversation)
    except (ValidationError, ValueError, KeyError, TypeError):
        return {"task_result": _failed("EXTRACTION_FAILED",
            "The request could not be interpreted reliably. Retry or clarify the allocation.",
            session["task"]["task_id"])}
    return {"interpretation": interpretation.model_dump(),
            "sequence": conversation["current_sequence"]}


def prepare(state: AllocationState, runtime: Runtime[AgentContext]):
    context = runtime.context
    interpretation = TurnInterpretation.model_validate(state["interpretation"])
    prepared = allocation_preparation.prepare(
        db_path=context.db_path, session_id=context.session_id, owner=context.owner,
        request_id=context.request_id, interpretation=interpretation, as_of=context.as_of,
        sequence=state["sequence"])
    if not prepared["ready"]:
        return {"preparation": prepared, "task_result": {
            "task_id": prepared["task"]["task_id"], "task_type": "allocation",
            "status": "blocked", "result": None, "issues": prepared["issues"]}}
    return {"preparation": prepared}


def load_allocation_skill(state: AllocationState, runtime: Runtime[AgentContext]):
    pinned = waiting_skill_snapshots(runtime.context, "allocation")
    item = pinned.get("allocation-recommendation") or skills.load(
        "allocation-recommendation", runtime.context.skill_root)
    if any(name not in TOOLS or not allowed_for_task(name, "allocation") for name in item["tools"]):
        return {"task_result": _failed("SKILL_TOOL_UNAVAILABLE",
            "The allocation instructions require an unavailable tool.",
            state["preparation"]["task"]["task_id"])}
    return {"loaded_skills": {item["name"]: item}}


def execute_allocation(state: AllocationState, runtime: Runtime[AgentContext]):
    history = state.get("messages", [])
    result = run_executor(runtime.context, task_type="allocation",
                          loaded_skills=state["loaded_skills"],
                          seed_history=history[:-1] if history else ())
    task_result = result.get("task_result") or _failed("INCOMPLETE_RECOMMENDATION",
        "No verified recommendation was saved.", state["preparation"]["task"]["task_id"])
    reply = final_text(result).strip()
    if task_result["status"] in ("blocked", "failed"):
        issues = task_result.get("issues") or []
        reply = issues[0].get("question", "The allocation could not be completed.") if issues else "The allocation could not be completed."
    return {"task_result": task_result, "reply": reply,
            "tool_results": result.get("tool_results", []),
            "pending_question": result.get("pending_question"),
            "loaded_skills": result.get("loaded_skills", state["loaded_skills"])}


def route_after_extract(state):
    return END if state.get("task_result") else "prepare"


def route_after_prepare(state):
    return END if state.get("task_result") else "load_skill"


def route_after_skill(state):
    return END if state.get("task_result") else "executor"


def build_graph():
    graph = StateGraph(AllocationState, context_schema=AgentContext)
    graph.add_node("extract", extract_fields)
    graph.add_node("prepare", prepare)
    graph.add_node("load_skill", load_allocation_skill)
    graph.add_node("executor", execute_allocation)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", route_after_extract, {"prepare": "prepare", END: END})
    graph.add_conditional_edges("prepare", route_after_prepare, {"load_skill": "load_skill", END: END})
    graph.add_conditional_edges("load_skill", route_after_skill, {"executor": "executor", END: END})
    graph.add_edge("executor", END)
    return graph.compile()
