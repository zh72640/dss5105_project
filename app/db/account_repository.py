"""Account and role lookups used by HTTP identity helpers."""


def count_non_admin_users(connection):
    return connection.execute(
        "SELECT COUNT(*) FROM desk_users WHERE role='user'").fetchone()[0]


def role_for_username(connection, username):
    row = connection.execute(
        "SELECT role FROM desk_users WHERE username=?", (username,)).fetchone()
    return row["role"] if row else None
