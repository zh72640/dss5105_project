def retrieve(connection, parsed):
    # MVP approved lookup rule: exact ID only. Never guess by customer.
    if not parsed.order_id:
        return None, "MISSING_ORDER_ID"
    row = connection.execute("SELECT * FROM orders WHERE order_id=?", (parsed.order_id,)).fetchone()
    if row is None:
        return None, "ORDER_NOT_FOUND"
    order = dict(row)
    for field in ("customer", "product", "category", "pieces", "order_date", "due_date"):
        value = getattr(parsed, field)
        stored = order[field]
        if value is not None and (str(value).casefold() != str(stored).casefold()):
            return order, "ORDER_FIELD_CONFLICT:" + field
    return order, None
