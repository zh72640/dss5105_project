"""New read-only helpers; existing SQLite repositories and schema remain untouched."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def saved_execution(db_path, request_id):
    if not request_id:
        return None
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        return execution_on_connection(connection, request_id)


def execution_on_connection(connection, request_id):
    row = connection.execute("SELECT telemetry_json FROM requests WHERE request_id=?", (request_id,)).fetchone()
    return json.loads(row[0]).get("execution") if row else None
