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
