"""Allocation-specific fixed preparation, Skill loading and guarded tool execution."""
from typing import TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.runtime import Runtime

from app.agent import skills
from app.agent.dynamic import AgentContext
from app.agent.intake import interpret_current_message
from app.agent.executor import run as run_executor, waiting_skill_snapshots
from app.schemas.chat import TurnInterpretation
from app.services.allocation.contracts import inspect_input, single_workshop_issues
from app.services.chat.completion import BASIC_ALLOCATION_POLICY
from app.services.chat import allocation_preparation
from app.tools.registry import TOOLS, allowed_for_task



class AllocationState(TypedDict, total=False):
    messages: list
    interpretation: dict
    sequence: int
    preparation: dict
    loaded_skills: dict
    task_result: dict
    tool_results: list
    pending_question: str | None
    skill_input: dict


def _failed(code, message, task_id=""):
    return {"task_id": task_id, "task_type": "allocation", "status": "failed",
            "result": None, "issues": [{"code": code, "field": "workflow",
                                         "severity": "blocking", "question": message}]}


def extract_fields(state: AllocationState, runtime: Runtime[AgentContext]):
    """Reuse a resolved follow-up, otherwise extract the current allocation turn."""
    if state.get("interpretation"):
        return {"interpretation": state["interpretation"], "sequence": state["sequence"]}
    return interpret_current_message(runtime.context)


def prepare(state: AllocationState, runtime: Runtime[AgentContext]):
    context = runtime.context
    interpretation = TurnInterpretation.model_validate(state["interpretation"])
    prepared = allocation_preparation.prepare(
        db_path=context.db_path, session_id=context.session_id, owner=context.owner,
        request_id=context.request_id, interpretation=interpretation, as_of=context.as_of,
        sequence=state["sequence"], user_message=context.user_message)
    skill_input, issues = inspect_input(prepared.get("skill_input") or prepared["task"]["draft"])
    issues += single_workshop_issues(prepared["task"]["draft"])
    if issues and prepared["ready"]:
        prepared = {**prepared, "ready": False, "issues": issues}
    if not prepared["ready"]:
        return {"preparation": prepared, "task_result": {
            "task_id": prepared["task"]["task_id"], "task_type": "allocation",
            "status": "blocked", "result": None, "issues": prepared["issues"]}}
    return {"preparation": prepared, "skill_input": skill_input}


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
                          seed_history=history[:-1] if history else (),
                          execution_policy=BASIC_ALLOCATION_POLICY, skill_input=state["skill_input"])
    task_result = result.get("task_result") or _failed("INCOMPLETE_RECOMMENDATION",
        "No verified recommendation was saved.", state["preparation"]["task"]["task_id"])
    return {"task_result": task_result,
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
