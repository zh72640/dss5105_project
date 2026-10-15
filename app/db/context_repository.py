"""Message reads used to assemble grounded interpretation context."""


def recent_messages(connection, session_id):
    return connection.execute(
        "SELECT sequence,role,content FROM chat_messages WHERE session_id=? ORDER BY sequence DESC LIMIT 24",
        (session_id,)).fetchall()


def message_at(connection, session_id, sequence):
    return connection.execute(
        "SELECT sequence,role,content FROM chat_messages WHERE session_id=? AND sequence=?",
        (session_id, sequence)).fetchone()
