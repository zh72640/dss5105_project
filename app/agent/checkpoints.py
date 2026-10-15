"""LangGraph SQLite checkpoint store bootstrap for Chat agent runs."""
import sqlite3
from contextlib import closing

from langgraph.checkpoint.sqlite import SqliteSaver


def initialize_checkpoints(db_path):
    """Prepare WAL and checkpoint tables before request handling starts."""
    with closing(sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)) as connection:
        SqliteSaver(connection).get_tuple({"configurable": {"thread_id": "__startup__"}})
