"""Agent run trace and replay persistence. All writes use the caller transaction."""
import json
from app.db.database import utc_now


def tool_call(connection, invocation_key):
    return connection.execute(
        "SELECT * FROM chat_agent_tool_calls WHERE invocation_key=?",
        (invocation_key,)).fetchone()


def task_state(connection, session_id):
    row = connection.execute(
        "SELECT state FROM chat_allocation_tasks WHERE session_id=?",
        (session_id,)).fetchone()
    return row["state"] if row else "UNAVAILABLE"


def record_call(connection, *, invocation_key, session_id, request_id, skill_name,
                skill_hash, tool_name, arguments, result, state_before, state_after,
                ignore_duplicate=False):
    verb = "INSERT OR IGNORE" if ignore_duplicate else "INSERT"
    connection.execute(f"""{verb} INTO chat_agent_tool_calls
        (invocation_key,session_id,request_id,skill_name,skill_hash,tool_name,arguments_json,
         result_json,state_before,state_after,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (invocation_key, session_id, request_id, skill_name, skill_hash, tool_name,
         json.dumps(arguments, ensure_ascii=False), json.dumps(result, ensure_ascii=False),
         state_before, state_after, utc_now()))


def record_event(connection, *, session_id, request_id, event_type, detail):
    connection.execute(
        "INSERT INTO chat_agent_events (session_id,request_id,event_type,detail_json,created_at) VALUES (?,?,?,?,?)",
        (session_id, request_id, event_type, json.dumps(detail, ensure_ascii=False), utc_now()))


def model_usage(connection, request_id):
    """Sum each persisted response once, including calls made before a resumed run."""
    rows = connection.execute("""SELECT detail_json FROM chat_agent_events
        WHERE request_id=? AND event_type='model_call' ORDER BY rowid""", (request_id,)).fetchall()
    calls = [json.loads(row["detail_json"]) for row in rows]
    totals = {key: sum((call.get("usage") or {}).get(key, 0) or 0 for call in calls)
              for key in ("input_tokens", "output_tokens", "total_tokens")}
    return {"model_calls": len(calls),
            "usage": totals if any(call.get("usage") for call in calls) else None}


def saved_messages(connection, session_id):
    return connection.execute("""SELECT role,content FROM chat_messages
        WHERE session_id=? ORDER BY sequence DESC LIMIT 40""", (session_id,)).fetchall()


def running_request(connection, session_id):
    return connection.execute(
        "SELECT request_id FROM chat_agent_runs WHERE session_id=? AND status='running'",
        (session_id,)).fetchone()


def run(connection, request_id):
    return connection.execute("SELECT * FROM chat_agent_runs WHERE request_id=?", (request_id,)).fetchone()


def start_run(connection, request_id, session_id, fingerprint, base_version):
    now = utc_now()
    connection.execute("INSERT INTO chat_agent_runs VALUES (?,?,?,?,?,?,?)",
                       (request_id, session_id, fingerprint, base_version, "running", now, now))


def set_run_status(connection, request_id, status):
    connection.execute("UPDATE chat_agent_runs SET status=?,updated_at=? WHERE request_id=?",
                       (status, utc_now(), request_id))


def record_turn_start(connection, *, turn_id, session_id, request_id, fingerprint,
                      base_version, input_json, telemetry_json):
    now = utc_now()
    connection.execute("""INSERT INTO chat_turns
        (turn_id,session_id,request_id,fingerprint,base_version,action,input_json,response_json,telemetry_json,created_at)
        VALUES (?,?,?,?,?,'message',?,?,?,?)""",
        (turn_id, session_id, request_id, fingerprint, base_version,
         input_json, "{}", telemetry_json, now))


def record_message_pair(connection, *, session_id, turn_id, sequence, user_message,
                        assistant_message, feedback_id, recommendation_id,
                        workflow="dynamic_agent_v1"):
    import uuid
    now = utc_now()
    for offset, role, content, mid in ((1, "user", user_message, uuid.uuid4().hex),
                                       (2, "assistant", assistant_message, feedback_id)):
        connection.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?,?)",
            (mid, session_id, turn_id, sequence + offset, role, content,
             json.dumps({"workflow": workflow, "recommendation_id": recommendation_id}), now))
    connection.execute("UPDATE chat_sessions SET version=version+1,updated_at=? WHERE session_id=?",
                       (now, session_id))


def finalize_turn(connection, turn_id, response_json, request_id):
    connection.execute("UPDATE chat_turns SET response_json=? WHERE turn_id=?", (response_json, turn_id))
    set_run_status(connection, request_id, "finished")


def ended_request(connection, request_id):
    row = connection.execute("""SELECT detail_json FROM chat_agent_events
        WHERE request_id=? AND event_type='request_ended' ORDER BY event_id DESC LIMIT 1""",
        (request_id,)).fetchone()
    return json.loads(row["detail_json"]) if row else None


def execution_scope(connection, session_id):
    row = connection.execute("""SELECT request_id FROM chat_agent_events
        WHERE session_id=? AND event_type='request_ended' ORDER BY event_id DESC LIMIT 1""",
        (session_id,)).fetchone()
    return row["request_id"] if row else None


def latest_model_stage(connection, request_id):
    row = connection.execute("""SELECT detail_json FROM chat_agent_events
        WHERE request_id=? AND event_type IN ('model_call_started','model_call')
        ORDER BY event_id DESC LIMIT 1""", (request_id,)).fetchone()
    return json.loads(row["detail_json"]).get("stage") if row else None


def latest_extraction(connection, request_id):
    row = connection.execute("""SELECT event_id,detail_json FROM chat_agent_events
        WHERE request_id=? AND event_type='allocation_extraction'
        ORDER BY event_id DESC LIMIT 1""", (request_id,)).fetchone()
    if row is None:
        return None
    result = json.loads(row['detail_json'])
    result['validation_recorded'] = connection.execute("""SELECT 1 FROM chat_agent_events
        WHERE request_id=? AND event_type='extraction_validation_failed' AND event_id>?
        LIMIT 1""", (request_id, row['event_id'])).fetchone() is not None
    return result
