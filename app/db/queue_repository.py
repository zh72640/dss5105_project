"""Persistence operations for workshop reservations."""


def get_queue(connection, workshop_id):
    return connection.execute("SELECT * FROM workshop_queue WHERE workshop_id=?", (workshop_id,)).fetchone()


def working_orders(connection, workshop_id):
    return connection.execute("SELECT rowid AS position,* FROM working_order WHERE workshop_id=? ORDER BY rowid", (workshop_id,)).fetchall()


def get_working_order(connection, order_id, workshop_id):
    return connection.execute("SELECT * FROM working_order WHERE order_id=? AND workshop_id=?", (order_id, workshop_id)).fetchone()


def set_remaining_at_position(connection, position, remaining):
    connection.execute("UPDATE working_order SET queue_remaining_days=? WHERE rowid=?", (remaining, position))


def set_aged_queue(connection, workshop_id, total, baseline, as_of):
    connection.execute("UPDATE workshop_queue SET current_queue_days=?,baseline_queue_days=?,as_of_date=? WHERE workshop_id=?", (total, baseline, as_of.isoformat(), workshop_id))


def set_working_remaining(connection, order_id, workshop_id, remaining):
    connection.execute("UPDATE working_order SET queue_remaining_days=? WHERE order_id=? AND workshop_id=?", (remaining, order_id, workshop_id))


def subtract_queue(connection, workshop_id, released):
    connection.execute("UPDATE workshop_queue SET current_queue_days=MAX(0,current_queue_days-?) WHERE workshop_id=?", (released, workshop_id))
