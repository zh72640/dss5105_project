"""Chat v2 LLM LangGraph entry: select Main Graph or resume a legacy checkpoint.

HTTP turns reach here via ``services.chat.service.turn`` → ``services.chat.agent_turns.turn``.
Offline Chat uses ``app.offline.graph`` (not this module).
"""
from contextlib import closing
import sqlite3

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.dynamic import build_graph as build_legacy_graph
from app.agent.main_graph import build_graph as build_main_graph, build_v1_graph, CURRENT_WORKFLOW, MAIN_WORKFLOWS
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
    config = {"configurable": {"thread_id": context.checkpoint_thread("chat-agent")}}
    with closing(sqlite3.connect(str(context.db_path), timeout=10, check_same_thread=False)) as connection:
        connection.execute("PRAGMA busy_timeout=10000")
        saver = SqliteSaver(connection)
        # Read the saved version before compiling: another graph can hide unknown pending nodes.
        stored = saver.get_tuple(config)
        version = stored.checkpoint.get('channel_values', {}).get('workflow_version') if stored else None
        saved_graph = (build_v1_graph(saver) if version == 'main_v1' else build_main_graph(saver)
                       if version in MAIN_WORKFLOWS else build_legacy_graph(saver))
        checkpoint = saved_graph.get_state(config)
        previous = checkpoint.values or {}
        same_request = previous.get('request_id') == context.request_id
        if checkpoint.next and not same_request:
            raise RunInProgress("Resume the interrupted request before starting another turn.")
        use_main = version in MAIN_WORKFLOWS or not checkpoint.next
        if use_main:
            model = registry.get_model("llm", context.model_key)
            if not callable(getattr(model, "bind_tools", None)):
                raise ModelSelectionError("TOOLS_UNSUPPORTED", "The selected model cannot use native tools.", 503)
        graph = saved_graph if same_request else build_main_graph(saver)
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
            initial["workflow_version"] = CURRENT_WORKFLOW
            initial.update(task_result={}, reply="", pending_question=None,
                           tool_results=[], loaded_skills={}, source_node=None,
                           explanation=None, response=None)
        else:
            initial.update(step_count=0, tool_call_count=0, plan=None,
                pending_question=None, tool_results=[],
                loaded_skills=values.get("loaded_skills", {}) if waiting else {},
                pinned_skills=list(values.get("loaded_skills", {})) if waiting else [])
        return graph.invoke(initial, config=config, context=context, durability="sync")
