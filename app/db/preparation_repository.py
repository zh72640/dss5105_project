"""Idempotent allocation preparation records."""
import json
from app.db.database import utc_now


def existing(connection, request_id):
    row = connection.execute(
        "SELECT detail_json FROM chat_agent_events WHERE request_id=? AND event_type='allocation_prepared' ORDER BY event_id DESC LIMIT 1",
        (request_id,)).fetchone()
    return json.loads(row["detail_json"]) if row else None


def record(connection, session_id, request_id, detail):
    connection.execute(
        "INSERT INTO chat_agent_events (session_id,request_id,event_type,detail_json,created_at) VALUES (?,?,?,?,?)",
        (session_id, request_id, "allocation_prepared",
         json.dumps(detail, ensure_ascii=False, allow_nan=False), utc_now()))


def recent(connection, session_id, limit=24):
    """Read bounded prior preparation snapshots for legacy alternative recovery."""
    rows = connection.execute(
        "SELECT detail_json FROM chat_agent_events WHERE session_id=? AND event_type='allocation_prepared' ORDER BY event_id DESC LIMIT ?",
        (session_id, limit)).fetchall()
    return [json.loads(row['detail_json']) for row in rows]
