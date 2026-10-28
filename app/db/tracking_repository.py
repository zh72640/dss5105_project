"""Read committed order decisions and lifecycle evidence in the caller's snapshot."""


def records(connection, order_id):
    return [dict(row) for row in connection.execute("""
        SELECT d.request_id,d.decision_status,d.decision_json,d.created_at,
               a.actor AS approval_actor,r.response_json,
               e.action,e.actor,e.reason,e.as_of_date,e.applied,e.before_json,e.after_json
        FROM decision_log d JOIN requests r USING(request_id)
        LEFT JOIN request_actors a USING(request_id)
        LEFT JOIN lifecycle_events e ON e.event_id=d.request_id
        WHERE d.order_id=? AND (d.decision_status='ALLOCATE' OR e.event_id IS NOT NULL)
        ORDER BY d.created_at,d.decision_id
        """, (order_id,))]


def completed_at(connection, order_id):
    row = connection.execute('SELECT completed_at FROM completed_order WHERE order_id=?', (order_id,)).fetchone()
    return row['completed_at'] if row else None
