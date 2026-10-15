"""Owner-scoped chat read models; mutations are coordinated by the chat service."""
import json


def snapshot(connection, session_id, owner):
    row = connection.execute('SELECT * FROM chat_sessions WHERE session_id=? AND owner_username=?', (session_id, owner)).fetchone()
    if not row:
        return None
    session = dict(row)
    for key in ('creation_key', 'creation_fingerprint'):
        session.pop(key)
    task = dict(connection.execute('SELECT * FROM chat_allocation_tasks WHERE session_id=?', (session_id,)).fetchone())
    for field in ('draft', 'sources', 'changes', 'issues', 'report'):
        task[field] = json.loads(task.pop(field + '_json'))
    session['task'] = task
    session['recommendation'] = latest_recommendation(connection, session_id)
    return session


def recommendation(row):
    if row is None:
        return None
    result = dict(row)
    result['result'] = json.loads(result.pop('result_json'))
    result['committed_result'] = json.loads(result.pop('committed_result_json') or 'null')
    result['source'] = 'chat_v2'
    return result


def latest_recommendation(connection, session_id):
    return recommendation(connection.execute('SELECT * FROM chat_recommendations WHERE session_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (session_id,)).fetchone())


def messages(connection, session_id, after=0, limit=50):
    rows = connection.execute('SELECT * FROM chat_messages WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?',
        (session_id, after, limit + 1)).fetchall()
    items = []
    for row in rows[:limit]:
        item = dict(row)
        item['metadata'] = json.loads(item.pop('metadata_json'))
        items.append(item)
    return dict(items=items, next_cursor=items[-1]['sequence'] if len(rows) > limit else None)


def recommendations(connection, owner, after=0, limit=50, status=None):
    rows = connection.execute('''SELECT r.*,r.rowid AS cursor,s.version AS session_version,t.state AS task_state
        FROM chat_recommendations r JOIN chat_sessions s USING(session_id)
        JOIN chat_allocation_tasks t ON t.task_id=r.task_id
        WHERE s.owner_username=? AND r.rowid>? AND (? IS NULL OR r.status=?)
        ORDER BY r.rowid LIMIT ?''', (owner, after, status, status, limit + 1)).fetchall()
    items = [recommendation(r) for r in rows[:limit]]
    return dict(items=items, next_cursor=items[-1]['cursor'] if len(rows) > limit else None)


def supersede_current(connection, session_id):
    connection.execute("UPDATE chat_recommendations SET status='superseded' WHERE session_id=? AND status='valid'", (session_id,))


def save_task(connection, task):
    connection.execute("""UPDATE chat_allocation_tasks SET task_version=?,state=?,draft_json=?,sources_json=?,changes_json=?,issues_json=?,report_json=? WHERE task_id=?""",
        (task["task_version"], task["state"], *(json.dumps(task[key], ensure_ascii=False, allow_nan=False)
          for key in ("draft", "sources", "changes", "issues", "report")), task["task_id"]))


def insert_recommendation(connection, session, result, facts_hash, plan_hash):
    import uuid
    from app.db.database import utc_now
    supersede_current(connection, session["session_id"])
    recommendation_id = uuid.uuid4().hex
    task = session["task"]
    connection.execute("""INSERT INTO chat_recommendations
        (recommendation_id,session_id,task_id,task_version,status,facts_hash,plan_hash,result_json,created_at)
        VALUES (?,?,?,?,'valid',?,?,?,?)""",
        (recommendation_id, session["session_id"], task["task_id"], task["task_version"],
         facts_hash, plan_hash, json.dumps(result, ensure_ascii=False, allow_nan=False), utc_now()))
    return latest_recommendation(connection, session["session_id"])


def replay_row(connection, request_id):
    return connection.execute('SELECT t.*,s.owner_username FROM chat_turns t JOIN chat_sessions s USING(session_id) WHERE request_id=?',
                              (request_id,)).fetchone()


def creation_row(connection, request_id):
    return connection.execute('SELECT * FROM chat_sessions WHERE creation_key=?', (request_id,)).fetchone()


def create_session(connection, *, session_id, owner, key, fingerprint, title, as_of, mode,
                   model_key, task_id, draft_json, now):
    connection.execute('''INSERT INTO chat_sessions
        (session_id,owner_username,creation_key,creation_fingerprint,title,status,version,business_date,mode,model_key,created_at,updated_at)
        VALUES (?,?,?,?,?,'OPEN',0,?,?,?,?,?)''',
        (session_id, owner, key, fingerprint, title[:80], as_of.isoformat(), mode, model_key, now, now))
    connection.execute('''INSERT INTO chat_allocation_tasks
        (task_id,session_id,task_version,state,draft_json,sources_json,changes_json,issues_json,report_json)
        VALUES (?,?,0,'COLLECTING',?,'{}','[]','[]','{}')''', (task_id, session_id, draft_json))


def supersede_recommendation(connection, recommendation_id):
    connection.execute("UPDATE chat_recommendations SET status='superseded' WHERE recommendation_id=? AND status='valid'",
                       (recommendation_id,))


def session_page(connection, owner, after, limit):
    return connection.execute('''SELECT rowid AS cursor,session_id,title,status,version,updated_at
        FROM chat_sessions WHERE owner_username=? AND (?=0 OR rowid<?) ORDER BY rowid DESC LIMIT ?''',
        (owner, after, after, limit + 1)).fetchall()


def trace_calls(connection, session_id, limit):
    return connection.execute("""SELECT invocation_key,request_id,skill_name,
        skill_hash,tool_name,arguments_json,result_json,state_before,state_after,created_at
        FROM chat_agent_tool_calls WHERE session_id=? ORDER BY rowid DESC LIMIT ?""",
        (session_id, limit)).fetchall()


def trace_events(connection, session_id, limit):
    return connection.execute("""SELECT request_id,event_type,detail_json,created_at
        FROM chat_agent_events WHERE session_id=? ORDER BY event_id DESC LIMIT ?""",
        (session_id, limit)).fetchall()


def confirmed_recommendation(connection, session_id, recommendation_id, owner):
    return connection.execute('''SELECT r.* FROM chat_recommendations r JOIN chat_sessions s USING(session_id)
        WHERE r.recommendation_id=? AND r.session_id=? AND s.owner_username=?''',
        (recommendation_id, session_id, owner)).fetchone()


def saved_turn_response(connection, turn_id):
    return connection.execute('SELECT response_json FROM chat_turns WHERE turn_id=?', (turn_id,)).fetchone()


def has_running_agent(connection, session_id):
    return connection.execute("SELECT 1 FROM chat_agent_runs WHERE session_id=? AND status='running'",
                              (session_id,)).fetchone() is not None


def order_row(connection, order_id):
    return connection.execute('SELECT * FROM orders WHERE order_id=?', (order_id,)).fetchone()


def workshop_rows(connection):
    return connection.execute('SELECT * FROM workshops ORDER BY workshop_id').fetchall()


def archive_session(connection, session_id):
    connection.execute("UPDATE chat_sessions SET status='ARCHIVED' WHERE session_id=?", (session_id,))


def start_turn(connection, *, turn_id, session_id, request_id, fingerprint, expected_version,
               action, input_json, telemetry_json, now):
    connection.execute('INSERT INTO chat_turns (turn_id,session_id,request_id,fingerprint,base_version,action,input_json,response_json,telemetry_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (turn_id, session_id, request_id, fingerprint, expected_version, action, input_json, '{}', telemetry_json, now))


def assign_actor(connection, request_id, owner):
    connection.execute('INSERT INTO request_actors VALUES (?,?)', (request_id, owner))


def insert_message(connection, *, message_id, session_id, turn_id, sequence, role, content, metadata_json, now):
    connection.execute('INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?,?)',
        (message_id, session_id, turn_id, sequence, role, content, metadata_json, now))


def increment_session(connection, session_id, now):
    connection.execute('UPDATE chat_sessions SET version=version+1,updated_at=? WHERE session_id=?',
                       (now, session_id))


def confirm_recommendation(connection, recommendation_id, turn_id, business_request_id,
                           feedback_message_id, committed_result_json):
    connection.execute("""UPDATE chat_recommendations SET status='confirmed',confirmation_turn_id=?,
        business_request_id=?,feedback_message_id=?,committed_result_json=? WHERE recommendation_id=?""",
        (turn_id, business_request_id, feedback_message_id, committed_result_json, recommendation_id))


def save_turn_response(connection, turn_id, response_json):
    connection.execute('UPDATE chat_turns SET response_json=? WHERE turn_id=?', (response_json, turn_id))
