"""Reusable Agent–Tool loop and legacy ``chat-agent:*`` checkpoint graph.

``executor.py`` uses this loop for Main Graph / Allocation tasks. ``runtime.py``
may still resume older session checkpoints compiled from ``build_graph`` here.
Keep both roles until an explicit checkpoint migration retires the legacy branch.
"""
from dataclasses import dataclass
from datetime import date
import json
import re
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from app.agent import skills
from app.schemas.tool import ToolFailure
from app.tools.registry import TOOLS, ALLOWED_TASK_STATES, allowed_for_task, invoke_tool
from app.db.database import Database
from app.db.chat_repository import snapshot
from app.llm.errors import ModelSelectionError, check_response, translate_error
from app.llm.registry import selection_metadata
from app.services.chat.completion import (
    BASIC_ALLOCATION_POLICY, allocation_call_error, allocation_execution_outcome,
)


MAX_MODEL_STEPS = 12
MAX_TOOL_CALLS = 32


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    loaded_skills: dict
    plan: dict | None
    pending_question: str | None
    step_count: int
    tool_call_count: int
    request_id: str
    tool_results: list
    pinned_skills: list[str]
    task_type: str
    task_result: dict
    execution_policy: str | None
    skill_input: dict | None


@dataclass(frozen=True)
class AgentContext:
    registry: object
    model_key: str
    owner: str
    db_path: str | Path
    session_id: str
    request_id: str
    user_message: str
    as_of: date
    skill_root: Path = skills.SKILL_ROOT
    execution_scope: str | None = None

    def checkpoint_thread(self, prefix):
        base = f"{prefix}:{self.session_id}"
        return f"{base}:after:{self.execution_scope}" if self.execution_scope else base


def available_tools(loaded, task_type="compat", task_state=None, execution_policy=None):
    names = {name for item in loaded.values() for name in item["tools"]}
    if execution_policy == BASIC_ALLOCATION_POLICY:
        from app.tools.registry import BASIC_ALLOCATION_TOOLS
        names &= BASIC_ALLOCATION_TOOLS
    visible = [name for name in sorted(names) if allowed_for_task(name, task_type) and
               (task_type != "allocation" or name not in ALLOWED_TASK_STATES or
                task_state in ALLOWED_TASK_STATES[name])]
    tools = [TOOLS[name] for name in visible]
    if task_type != "allocation":
        tools = [TOOLS["load_skill"], *tools]
    return tools


def system_message(context, loaded, *, execution_policy=None, skill_input=None):
    from app.prompts import get_registry
    with Database(context.db_path) as db:
        current = snapshot(db.connection, context.session_id, context.owner)
    if current is None:
        raise ToolFailure("SESSION_NOT_FOUND", "The session cannot be accessed by this account.")
    overview = [{"name": item.name, "description": item.description, "triggers": item.triggers}
                for item in skills.discover(context.skill_root).values()]
    instructions = {name: {"hash": item["hash"], "content": item["content"]}
                    for name, item in loaded.items()}
    facts = {"task": current["task"], "recommendation": current["recommendation"],
             "business_date": current["business_date"], "session_version": current["version"]}
    if execution_policy == BASIC_ALLOCATION_POLICY:
        bundle = get_registry().render("allocation.execute",
            variables={"loaded": instructions, "facts": facts, "skill_input": skill_input})
    else:
        bundle = get_registry().render("agent.reply",
            variables={"skills": overview, "loaded": instructions, "facts": facts})
    return SystemMessage(content=bundle.as_messages()[0]["content"]), bundle.metadata


def record_model_start(context, stage):
    """Persist the attempted stage even when the provider returns no response."""
    from app.db import agent_repository
    with Database(context.db_path) as db:
        with db.transaction() as connection:
            agent_repository.record_event(connection, session_id=context.session_id,
                request_id=context.request_id, event_type="model_call_started", detail={"stage": stage})


def record_model_response(context, stage, message, prompt=None):
    """Persist one actual model response, including its native usage and audit identity."""
    from app.db import agent_repository
    spec = context.registry.resolve("llm", context.model_key)
    prompt = prompt or {}
    metadata = getattr(message, "response_metadata", {}) or {}
    detail = {"stage": stage, "selection": selection_metadata("llm", spec, prompt.get("content_hash")),
              "prompt": prompt, "usage": getattr(message, "usage_metadata", None),
              "finish_reason": metadata.get("finish_reason", metadata.get("stop_reason")),
              "tool_call_ids": [call.get("id") for call in getattr(message, "tool_calls", [])]}
    with Database(context.db_path) as db:
        with db.transaction() as connection:
            agent_repository.record_event(connection, session_id=context.session_id,
                request_id=context.request_id, event_type="model_call", detail=detail)


def model_node(state: AgentState, runtime: Runtime[AgentContext]):
    count = state.get("step_count", 0)
    if count >= MAX_MODEL_STEPS:
        return {"messages": [AIMessage(content="The execution limit was reached. Please continue in the same session.")],
                "step_count": count + 1}
    context = runtime.context
    loaded = state.get("loaded_skills", {})
    history = state.get("messages", [])[-40:]
    with Database(context.db_path) as db:
        current = snapshot(db.connection, context.session_id, context.owner)
    if current is None:
        raise ToolFailure("SESSION_NOT_FOUND", "The session is unavailable to this account.")
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    if not callable(getattr(model, "bind_tools", None)):
        raise ModelSelectionError("TOOLS_UNSUPPORTED", "The selected model cannot use native tools.", 503)
    system, prompt = system_message(context, loaded, execution_policy=state.get("execution_policy"),
                                    skill_input=state.get("skill_input"))
    record_model_start(context, "tool_loop")
    try:
        answer = model.bind_tools(available_tools(loaded, state.get("task_type", "compat"),
            current["task"]["state"], state.get("execution_policy"))).invoke([system, *history])
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    if not isinstance(answer, AIMessage) or not hasattr(answer, "tool_calls"):
        raise ModelSelectionError("TOOLS_UNSUPPORTED", "The selected model cannot use native tools.", 503)
    stage = "allocation_stop" if state.get("execution_policy") == BASIC_ALLOCATION_POLICY else "reply"
    record_model_response(context, "tool_loop" if answer.tool_calls else stage, answer, prompt)
    check_response(answer, require_text=not bool(answer.tool_calls) and stage != "allocation_stop")
    return {"messages": [answer], "step_count": count + 1}


def after_model(state):
    message = state["messages"][-1]
    return "tools" if getattr(message, "tool_calls", None) else "guard"


def _tool_result(context, state, call, loaded, plan):
    from app.db import agent_repository

    name = call["name"]
    args = call.get("args") or {}
    call_id = call.get("id")
    if not call_id:
        raise ToolFailure("TOOL_CALL_ID_REQUIRED", "A native tool call ID is required for replay safety.")
    invocation_key = f"{context.request_id}:{call_id}"
    if state.get("execution_policy") == BASIC_ALLOCATION_POLICY:
        error = allocation_call_error(state.get("tool_results", []), name)
        if error:
            raise ToolFailure(*error)
    if name == "record_production_event":
        return _production_result(context, invocation_key, args, loaded)
    with Database(context.db_path) as db:
        with db.transaction() as connection:
            cached = agent_repository.tool_call(connection, invocation_key)
            if cached:
                if cached["tool_name"] != name or json.loads(cached["arguments_json"]) != args:
                    raise ToolFailure("TOOL_CALL_CONFLICT", "A replayed tool call changed its name or arguments.")
                replayed = json.loads(cached["result_json"])
                data = replayed.get("data") if replayed.get("ok") else None
                return (replayed, data if name == "load_skill" else None,
                        data if name == "compute_plan" else None,
                        data.get("question") if name == "ask_user" and data else None)
            current = snapshot(connection, context.session_id, context.owner)
            if current is None or current["status"] != "OPEN":
                raise ToolFailure("SESSION_NOT_FOUND", "The session is unavailable to this account.")
            before = current["task"]["state"]
            selected = None
            item = None
            data = None
            next_plan = None
            pending = None
            try:
                if name == "load_skill":
                    if state.get("task_type") == "allocation" and args.get("name") != "allocation-recommendation":
                        raise ToolFailure("SKILL_NOT_ALLOWED", "This Skill is not available for the allocation task.")
                    if args.get("name") in state.get("pinned_skills", ()) and args.get("name") in loaded:
                        item = loaded[args["name"]]
                        data = item
                    else:
                        data = invoke_tool(
                            "load_skill", args, connection=connection, session=current,
                            as_of=context.as_of, user_message=context.user_message,
                            skill_root=context.skill_root)
                        item = data
                    if set(data["tools"]) - set(TOOLS):
                        raise ToolFailure("UNREGISTERED_TOOL", "The Skill names an unregistered tool.")
                    selected = data["name"]
                else:
                    if not allowed_for_task(name, state.get("task_type", "compat")):
                        raise ToolFailure("TOOL_NOT_ALLOWED", "This tool is not allowed for the current task.")
                    selected = next((skill for skill in loaded.values() if name in skill["tools"]), None)
                    if selected is None:
                        raise ToolFailure("TOOL_NOT_ALLOWED", "Load a Skill that permits this tool in the current session.")
                    data = invoke_tool(
                        name, args, connection=connection, session=current,
                        as_of=context.as_of, user_message=context.user_message, plan=plan,
                        allocation_input=(state.get("skill_input") or {})
                            if state.get("execution_policy") == BASIC_ALLOCATION_POLICY else None)
                    if name == "compute_plan":
                        next_plan = data
                    if name == "ask_user":
                        pending = data.get("question")
                result = {"ok": True, "data": data}
            except ToolFailure as error:
                result = {"ok": False, "error": {"code": error.code, "message": str(error)}}
            after = agent_repository.task_state(connection, context.session_id)
            selected_name = selected if isinstance(selected, str) else selected["name"] if selected else None
            selected_hash = item["hash"] if item else selected["hash"] if isinstance(selected, dict) else None
            agent_repository.record_call(connection, invocation_key=invocation_key,
                session_id=context.session_id, request_id=context.request_id,
                skill_name=selected_name, skill_hash=selected_hash, tool_name=name,
                arguments=args, result=result, state_before=before, state_after=after)
            agent_repository.record_event(connection, session_id=context.session_id,
                request_id=context.request_id, event_type="tool_result",
                detail={"tool": name, "skill": selected_name, "skill_hash": selected_hash,
                        "arguments": args, "result": result,
                        "state_before": before, "state_after": after})
            return result, item, next_plan, pending


def _production_result(context, invocation_key, args, loaded):
    from app.db import agent_repository

    selected = next((skill for skill in loaded.values()
                     if "record_production_event" in skill["tools"]), None)
    if selected is None:
        raise ToolFailure("TOOL_NOT_ALLOWED", "Load the production Skill before this tool.")
    with Database(context.db_path) as db:
        cached = agent_repository.tool_call(db.connection, invocation_key)
        if cached:
            if json.loads(cached["arguments_json"]) != args or cached["tool_name"] != "record_production_event":
                raise ToolFailure("TOOL_CALL_CONFLICT", "A replayed production call changed its arguments.")
            return json.loads(cached["result_json"]), None, None, None
        current = snapshot(db.connection, context.session_id, context.owner)
        if current is None or current["status"] != "OPEN":
            raise ToolFailure("SESSION_NOT_FOUND", "The session is unavailable to this account.")
        before = current["task"]["state"]
    result = invoke_tool(
        "record_production_event", args,
        connection=None, session=current, as_of=context.as_of,
        user_message=context.user_message, owner=context.owner,
        db_path=context.db_path, invocation_key=invocation_key)
    with Database(context.db_path) as db:
        with db.transaction() as connection:
            cached = agent_repository.tool_call(connection, invocation_key)
            if cached:
                return json.loads(cached["result_json"]), None, None, None
            after = agent_repository.task_state(connection, context.session_id)
            agent_repository.record_call(connection, invocation_key=invocation_key,
                session_id=context.session_id, request_id=context.request_id,
                skill_name=selected["name"], skill_hash=selected["hash"],
                tool_name="record_production_event", arguments=args, result=result,
                state_before=before, state_after=after)
            agent_repository.record_event(connection, session_id=context.session_id,
                request_id=context.request_id, event_type="production_result",
                detail={"arguments": args, "result": result, "skill_hash": selected["hash"],
                        "state_before": before, "state_after": after})
    return result, None, None, None


def _record_rejection(context, call, result, loaded):
    from app.db import agent_repository

    name = call.get("name", "unknown")
    args = call.get("args") or {}
    selected = next((skill for skill in loaded.values() if name in skill["tools"]), None)
    with Database(context.db_path) as db:
        with db.transaction() as connection:
            current = snapshot(connection, context.session_id, context.owner)
            before = current["task"]["state"] if current else "UNAVAILABLE"
            key = f"{context.request_id}:{call['id']}" if call.get("id") else None
            if key:
                agent_repository.record_call(connection, invocation_key=key,
                    session_id=context.session_id, request_id=context.request_id,
                    skill_name=selected["name"] if selected else None,
                    skill_hash=selected["hash"] if selected else None,
                    tool_name=name, arguments=args, result=result,
                    state_before=before, state_after=before, ignore_duplicate=True)
            agent_repository.record_event(connection, session_id=context.session_id,
                request_id=context.request_id, event_type="rejected_tool_call",
                detail={"tool": name, "arguments": args, "result": result,
                        "state_before": before, "state_after": before,
                        "skill_hash": selected["hash"] if selected else None})


def tool_node(state: AgentState, runtime: Runtime[AgentContext]):
    loaded = dict(state.get("loaded_skills", {}))
    plan = state.get("plan")
    pending = None
    messages = []
    results = list(state.get("tool_results", []))
    call_count = state.get("tool_call_count", 0)
    for call in state["messages"][-1].tool_calls:
        if (state.get("execution_policy") == BASIC_ALLOCATION_POLICY and
                allocation_execution_outcome(results)[0]):
            result, skill, next_plan, question = ({"ok": False, "error": {
                "code": "TASK_EXECUTION_FINISHED", "message": "The allocation execution has already ended."}},
                None, None, None)
            _record_rejection(runtime.context, call, result, loaded)
        elif pending:
            result, skill, next_plan, question = ({"ok": False, "error": {
                "code": "USER_INPUT_REQUIRED", "message": "Answer the pending question before another action."}},
                None, None, None)
            _record_rejection(runtime.context, call, result, loaded)
        elif call_count >= MAX_TOOL_CALLS:
            result, skill, next_plan, question = ({"ok": False, "error": {
                "code": "EXECUTION_LIMIT", "message": "The tool execution limit was reached for this turn."}},
                None, None, None)
            _record_rejection(runtime.context, call, result, loaded)
        else:
            try:
                result, skill, next_plan, question = _tool_result(
                    runtime.context, {**state, "tool_results": results}, call, loaded, plan)
            except ToolFailure as error:
                result, skill, next_plan, question = ({"ok": False, "error": {"code": error.code,
                    "message": str(error)}}, None, None, None)
                _record_rejection(runtime.context, call, result, loaded)
        call_count += 1
        if skill and result["ok"]:
            loaded[skill["name"]] = skill
        if call["name"] == "update_constraints" and result["ok"]:
            plan = None
        if result.get("error", {}).get("code") == "STALE_PLAN":
            plan = None
        if next_plan is not None and result["ok"]:
            plan = next_plan
        if question and result["ok"]:
            pending = question
        messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False),
                                    tool_call_id=call["id"], name=call["name"]))
        results.append({"name": call["name"], "arguments": call.get("args") or {}, "result": result})
    return {"messages": messages, "loaded_skills": loaded, "plan": plan,
            "pending_question": pending, "tool_results": results,
            "tool_call_count": call_count}


def after_tools(state):
    if (state.get("execution_policy") == BASIC_ALLOCATION_POLICY and
            allocation_execution_outcome(state.get("tool_results", []))[0]):
        return "guard"
    return "guard" if state.get("pending_question") else "model"


def completion_guard(state: AgentState, runtime: Runtime[AgentContext]):
    from app.services.chat import service as chat
    from app.services.chat.completion import evaluate_allocation, evaluate_compat
    session = chat.inspect(runtime.context.session_id, owner=runtime.context.owner,
                           db_path=runtime.context.db_path)
    if state.get("task_type") == "allocation":
        result = evaluate_allocation(session, state.get("tool_results", []),
            state.get("pending_question"), state.get("step_count", 0) > MAX_MODEL_STEPS or
            state.get("tool_call_count", 0) > MAX_TOOL_CALLS,
            execution_policy=state.get("execution_policy"))
    else:
        result = evaluate_compat(session, state.get("tool_results", []), state.get("pending_question"))
    return {"task_result": result}


def build_graph(checkpointer):
    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("model", model_node)
    graph.add_node("tools", tool_node)
    graph.add_node("guard", completion_guard)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", after_model, {"tools": "tools", "guard": "guard"})
    graph.add_conditional_edges("tools", after_tools, {"model": "model", "guard": "guard"})
    graph.add_edge("guard", END)
    return graph.compile(checkpointer=checkpointer)


def final_text(state):
    if state.get("pending_question"):
        return state["pending_question"]
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            if isinstance(content, str):
                answer = content
            if isinstance(content, list):
                answer = "".join(item.get("text", "") for item in content if isinstance(item, dict))
            if isinstance(content, (str, list)):
                return ("Please continue in English in this session." if re.search(r"[\u4e00-\u9fff]", answer)
                        else answer)
    return "Please continue in this session."
