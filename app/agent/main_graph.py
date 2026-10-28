"""Generic task routing and TaskResult handling for LLM Chat v2."""
import json
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from app.agent.allocation_graph import build_graph as build_allocation_graph
from app.agent.explanation import explain
from app.agent.response import assemble
from app.agent.dynamic import AgentContext, final_text, record_model_response, record_model_start
from app.llm.errors import BackendError, check_response, check_structured, text_content, translate_error
from app.llm.json_output import json_text
from app.agent.executor import run as run_executor
from app.prompts import get_registry
from app.services.chat import service as chat
from app.schemas.agent import ExplanationResult

CURRENT_WORKFLOW = 'main_v2'
MAIN_WORKFLOWS = frozenset({'main_v1', CURRENT_WORKFLOW})


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
    source_node: str | None
    explanation: ExplanationResult | None
    response: dict | None


def identify(state: MainState, runtime: Runtime[AgentContext]):
    context = runtime.context
    session = chat.inspect(context.session_id, owner=context.owner, db_path=context.db_path)
    bundle = get_registry().render("agent.intent",
        variables={"task": {"task_id": session["task"]["task_id"],
                            "state": session["task"]["state"],
                            "pending_issues": session["task"]["issues"]},
                   "output_schema": INTENT_SCHEMA},
        user_message=context.user_message)
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    record_model_start(context, "intent")
    try:
        if spec.output_method == "prompt":
            raw = model.invoke(bundle.as_messages())
        else:
            result = model.with_structured_output({"title": "AgentIntent", **INTENT_SCHEMA},
                method=spec.output_method,
                include_raw=True).invoke(bundle.as_messages())
            raw = result.get("raw") if isinstance(result, dict) else None
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    if raw is not None:
        record_model_response(context, "intent", raw, bundle.metadata)
    try:
        parsed = json.loads(json_text(text_content(check_response(raw)))) if spec.output_method == "prompt" else check_structured(result)[0]
        route = parsed.get("task_type")
        if route not in ("allocation", "compat"):
            raise ValueError("INVALID_TASK_ROUTE")
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"route": "failed", "workflow_version": state.get('workflow_version', CURRENT_WORKFLOW),
                "task_result": {"task_id": session["task"]["task_id"], "task_type": "unknown",
                                "status": "failed", "result": None,
                                "issues": [{"code": "INTENT_FAILED", "field": "workflow",
                                            "severity": "blocking",
                                            "question": "The request could not be classified reliably. Please retry or clarify."}]}}
    return {"route": route, "workflow_version": state.get('workflow_version', CURRENT_WORKFLOW)}


def allocation(state: MainState, runtime: Runtime[AgentContext]):
    subgraph = build_allocation_graph()
    output = subgraph.invoke({"messages": state.get("messages", [])},
                             context=runtime.context)
    result = output["task_result"]
    return {"task_result": result, "source_node": "allocation",
            "tool_results": output.get("tool_results", []),
            "pending_question": output.get("pending_question"),
            "loaded_skills": output.get("loaded_skills", {})}


def respond(state: MainState, runtime: Runtime[AgentContext]):
    """Resume the combined response node of a pinned main_v1 checkpoint."""
    result = state["task_result"]
    if result["status"] in ("blocked", "failed"):
        messages = list(dict.fromkeys(item["question"] for item in result.get("issues", [])
                                    if item.get("question")))
        return {"reply": " ".join(messages) or "The task could not be completed."}
    context = runtime.context
    bundle = get_registry().render("agent.response", variables={"task_result": result},
                                   user_message=context.user_message)
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    record_model_start(context, "response")
    try:
        raw = model.invoke(bundle.as_messages())
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    record_model_response(context, "response", raw, bundle.metadata)
    check_response(raw)
    if getattr(raw, "tool_calls", None):
        raise BackendError("model_unexpected_response_tools", retryable=False)
    return {"reply": final_text({"messages": [raw]}).strip()}


def compatibility(state: MainState, runtime: Runtime[AgentContext]):
    history = state.get("messages", [])
    output = run_executor(runtime.context, task_type="compat",
                          seed_history=history[:-1] if history else ())
    return {"task_result": output["task_result"], "reply": final_text(output), "source_node": "compat",
            "tool_results": output.get("tool_results", []),
            "pending_question": output.get("pending_question"),
            "loaded_skills": output.get("loaded_skills", {})}


def finish(state: MainState):
    result = state["task_result"]
    reply = state.get("reply", "")
    if not reply and result["status"] in ("blocked", "failed") and result.get("issues"):
        reply = result["issues"][0]["question"]
    return {"reply": reply}


def build_graph(checkpointer):
    return _build_graph(checkpointer, legacy=False)


def build_v1_graph(checkpointer):
    """Keep saved node names and edges until main_v1 requests finish."""
    return _build_graph(checkpointer, legacy=True)


def _build_graph(checkpointer, *, legacy):
    graph = StateGraph(MainState, context_schema=AgentContext)
    graph.add_node("identify", identify)
    graph.add_node("allocation", allocation)
    graph.add_node("compat", compatibility)
    graph.add_node("finish", finish)
    if legacy:
        graph.add_node("respond", respond)
    else:
        graph.add_node("explanation", explain)
        graph.add_node("response", assemble)
    graph.add_edge(START, "identify")
    graph.add_conditional_edges("identify", lambda state: state["route"],
                                {"allocation": "allocation", "compat": "compat", "failed": "finish"})
    if legacy:
        graph.add_edge("allocation", "respond")
        graph.add_edge("respond", "finish")
    else:
        graph.add_edge("allocation", "explanation")
        graph.add_edge("explanation", "response")
        graph.add_edge("response", "finish")
    graph.add_edge("compat", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
