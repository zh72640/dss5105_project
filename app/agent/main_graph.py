"""Generic task routing and TaskResult handling for LLM Chat v2."""
import json
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from app.agent.allocation_graph import build_graph as build_allocation_graph
from app.agent.dynamic import AgentContext, final_text
from app.agent.executor import run as run_executor
from app.prompts import get_registry
from app.services import chat


INTENT_SCHEMA = {
    "type": "object", "properties": {
        "task_type": {"type": "string", "enum": ["allocation", "compat"]}
    }, "required": ["task_type"], "additionalProperties": False,
}


class MainState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    request_id: str
    route: str
    task_result: dict
    reply: str
    workflow_version: str
    loaded_skills: dict
    tool_results: list
    pending_question: str | None


def identify(state: MainState, runtime: Runtime[AgentContext]):
    context = runtime.context
    session = chat.inspect(context.session_id, owner=context.owner, db_path=context.db_path)
    bundle = get_registry().render("agent.intent",
        variables={"task": {"task_id": session["task"]["task_id"],
                            "state": session["task"]["state"],
                            "pending_issues": session["task"]["issues"]},
                   "output_schema": INTENT_SCHEMA},
        user_message=context.user_message)
    try:
        response, _ = context.registry.invoke_task("llm", context.model_key, bundle)
        parsed = json.loads(response["text"])
        route = parsed.get("task_type")
        if route not in ("allocation", "compat"):
            raise ValueError("INVALID_TASK_ROUTE")
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"route": "failed", "workflow_version": "main_v1",
                "task_result": {"task_id": session["task"]["task_id"], "task_type": "unknown",
                                "status": "failed", "result": None,
                                "issues": [{"code": "INTENT_FAILED", "field": "workflow",
                                            "severity": "blocking",
                                            "question": "The request could not be classified reliably. Please retry or clarify."}]}}
    return {"route": route, "workflow_version": "main_v1"}


def allocation(state: MainState, runtime: Runtime[AgentContext]):
    subgraph = build_allocation_graph()
    output = subgraph.invoke({"messages": state.get("messages", [])},
                             context=runtime.context)
    result = output["task_result"]
    reply = output.get("reply") or (
        result["issues"][0]["question"] if result.get("issues")
        else "Please continue in this session.")
    return {"task_result": result, "reply": reply,
            "tool_results": output.get("tool_results", []),
            "pending_question": output.get("pending_question"),
            "loaded_skills": output.get("loaded_skills", {})}


def compatibility(state: MainState, runtime: Runtime[AgentContext]):
    history = state.get("messages", [])
    output = run_executor(runtime.context, task_type="compat",
                          seed_history=history[:-1] if history else ())
    return {"task_result": output["task_result"], "reply": final_text(output),
            "tool_results": output.get("tool_results", []),
            "pending_question": output.get("pending_question"),
            "loaded_skills": output.get("loaded_skills", {})}


def finish(state: MainState):
    result = state["task_result"]
    reply = state.get("reply", "")
    if result["status"] in ("blocked", "failed") and result.get("issues"):
        reply = result["issues"][0]["question"]
    return {"reply": reply}


def build_graph(checkpointer):
    graph = StateGraph(MainState, context_schema=AgentContext)
    graph.add_node("identify", identify)
    graph.add_node("allocation", allocation)
    graph.add_node("compat", compatibility)
    graph.add_node("finish", finish)
    graph.add_edge(START, "identify")
    graph.add_conditional_edges("identify", lambda state: state["route"],
                                {"allocation": "allocation", "compat": "compat", "failed": "finish"})
    graph.add_edge("allocation", "finish")
    graph.add_edge("compat", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
