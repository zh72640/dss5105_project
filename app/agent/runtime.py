"""Chat v2 LLM LangGraph entry: select Main Graph or resume a legacy checkpoint.

HTTP turns reach here via ``services.chat.turn`` → ``services.agent_chat.turn``.
Offline Chat uses ``app.offline.graph`` (not this module).
"""
from contextlib import closing
import sqlite3

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.dynamic import build_graph as build_legacy_graph
from app.agent.main_graph import build_graph as build_main_graph
from app.db.database import Database
from app.db import agent_repository
from app.llm.errors import ModelSelectionError


class RunInProgress(RuntimeError):
    pass


def _saved_history(db_path, session_id):
    with Database(db_path) as db:
        rows = agent_repository.saved_messages(db.connection, session_id)
    return [HumanMessage(content=row["content"]) if row["role"] == "user"
            else AIMessage(content=row["content"])
            for row in reversed(rows) if row["role"] in ("user", "assistant")]


def run(context, registry):
    """Resume the saved graph run or start one using the current task's graph."""
    config = {"configurable": {"thread_id": f"chat-agent:{context.session_id}"}}
    with closing(sqlite3.connect(str(context.db_path), timeout=10, check_same_thread=False)) as connection:
        connection.execute("PRAGMA busy_timeout=10000")
        saver = SqliteSaver(connection)
        legacy_graph = build_legacy_graph(saver)
        checkpoint = legacy_graph.get_state(config)
        previous = checkpoint.values or {}
        use_main = previous.get("workflow_version") == "main_v1" or not checkpoint.next
        if use_main:
            model = registry.get_model("llm", context.model_key)
            if not callable(getattr(model, "bind_tools", None)):
                raise ModelSelectionError("TOOLS_UNSUPPORTED", "The selected model cannot use native tools.", 503)
        graph = build_main_graph(saver) if use_main else legacy_graph
        checkpoint = graph.get_state(config)
        values = checkpoint.values or {}
        if values.get("request_id") == context.request_id:
            return (graph.invoke(None, config=config, context=context, durability="sync")
                    if checkpoint.next else values)
        if checkpoint.next:
            raise RunInProgress("Resume the interrupted request before starting another turn.")
        waiting = bool(values.get("pending_question"))
        history = [] if values.get("messages") else _saved_history(context.db_path, context.session_id)
        initial = {"messages": [*history, HumanMessage(content=context.user_message)],
                   "request_id": context.request_id}
        if use_main:
            initial["workflow_version"] = "main_v1"
        else:
            initial.update(step_count=0, tool_call_count=0, plan=None,
                pending_question=None, tool_results=[],
                loaded_skills=values.get("loaded_skills", {}) if waiting else {},
                pinned_skills=list(values.get("loaded_skills", {})) if waiting else [])
        return graph.invoke(initial, config=config, context=context, durability="sync")
