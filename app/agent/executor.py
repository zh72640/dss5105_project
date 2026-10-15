"""Checkpointed, reusable LangGraph model and tool executor."""
from contextlib import closing
import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.dynamic import build_graph


def run(context, *, task_type, loaded_skills=None, seed_history=()):
    """Resume one request or run a fresh bounded tool loop."""
    config = {"configurable": {"thread_id": f"agent-executor:{task_type}:{context.session_id}"}}
    with closing(sqlite3.connect(str(context.db_path), timeout=10, check_same_thread=False)) as connection:
        connection.execute("PRAGMA busy_timeout=10000")
        graph = build_graph(SqliteSaver(connection))
        checkpoint = graph.get_state(config)
        values = checkpoint.values or {}
        if values.get("request_id") == context.request_id:
            return (graph.invoke(None, config=config, context=context, durability="sync")
                    if checkpoint.next else values)
        if checkpoint.next:
            raise ValueError("AGENT_RUN_IN_PROGRESS")
        waiting = bool(values.get("pending_question"))
        loaded = values.get("loaded_skills", {}) if waiting else (loaded_skills or {})
        messages = ([HumanMessage(content=context.user_message)] if values.get("messages")
                    else [*seed_history, HumanMessage(content=context.user_message)])
        return graph.invoke({
            "messages": messages, "request_id": context.request_id, "task_type": task_type,
            "step_count": 0, "tool_call_count": 0, "plan": None,
            "pending_question": None, "tool_results": [],
            "loaded_skills": loaded, "pinned_skills": list(loaded) if waiting else [],
            "task_result": {},
        }, config=config, context=context, durability="sync")


def waiting_skill_snapshots(context, task_type):
    config = {"configurable": {"thread_id": f"agent-executor:{task_type}:{context.session_id}"}}
    with closing(sqlite3.connect(str(context.db_path), timeout=10, check_same_thread=False)) as connection:
        checkpoint = build_graph(SqliteSaver(connection)).get_state(config)
        values = checkpoint.values or {}
        return values.get("loaded_skills", {}) if values.get("pending_question") else {}
