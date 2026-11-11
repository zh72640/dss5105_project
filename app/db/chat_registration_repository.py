"""Durable registration drafts and request preparation results."""
import json
from app.db import order_intake_repository as reviews
from app.db.database import utc_now


def get(connection, session_id):
    row = connection.execute('SELECT * FROM chat_order_registration WHERE session_id=?', (session_id,)).fetchone()
    if not row:
        return None
    task = dict(row)
    task['draft'] = json.loads(task.pop('draft_json'))
    task['issues'] = json.loads(task.pop('issues_json'))
    row = reviews.review_by_id(connection, task['review_id']) if task['review_id'] else None
    task['review'] = reviews.review_snapshot(connection, row) if row else None
    return task


def save(connection, task):
    connection.execute('''INSERT INTO chat_order_registration
        (session_id,task_id,status,draft_json,issues_json,review_id,updated_at) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET task_id=excluded.task_id,status=excluded.status,
        draft_json=excluded.draft_json,issues_json=excluded.issues_json,review_id=excluded.review_id,
        updated_at=excluded.updated_at''', (task['session_id'], task['task_id'], task['status'],
        json.dumps(task['draft']), json.dumps(task['issues']), task['review_id'], utc_now()))


def step(connection, request_id):
    return connection.execute('SELECT * FROM chat_registration_steps WHERE request_id=?', (request_id,)).fetchone()


def save_step(connection, request_id, session_id, fingerprint, result):
    connection.execute('INSERT INTO chat_registration_steps VALUES (?,?,?,?)',
                       (request_id, session_id, fingerprint, json.dumps(result)))
