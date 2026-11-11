"""Order registration persistence. The caller owns transactions and policy."""
import json

from app.schemas.order_intake import EDITABLE_FIELDS, ORDER_FIELDS


def review_by_request(connection, request_id):
    return connection.execute("SELECT * FROM order_intake_reviews WHERE request_id=?", (request_id,)).fetchone()


def review_by_id(connection, review_id):
    return connection.execute("SELECT * FROM order_intake_reviews WHERE review_id=?", (review_id,)).fetchone()


def decision_by_request(connection, request_id):
    return connection.execute("SELECT * FROM order_intake_decisions WHERE request_id=?", (request_id,)).fetchone()


def decision_by_review(connection, review_id):
    return connection.execute("SELECT * FROM order_intake_decisions WHERE review_id=?", (review_id,)).fetchone()


def review_snapshot(connection, row):
    review = json.loads(row['review_json'])
    decision = decision_by_review(connection, row['review_id'])
    if decision:
        review['decision'] = {**json.loads(decision['response_json']),
                              'evidence': json.loads(decision['decision_json'])}
    return review


def save_review(connection, review, fingerprint):
    connection.execute("""INSERT INTO order_intake_reviews
        (review_id,request_id,actor,order_id,fingerprint,review_json,created_at) VALUES (?,?,?,?,?,?,?)""",
        (review["review_id"], review["request_id"], review["actor"], review["order_id"], fingerprint,
         json.dumps(review), review["created_at"]))


def save_decision(connection, response, evidence, fingerprint, status):
    connection.execute("""INSERT INTO order_intake_decisions
        (request_id,review_id,actor,action,fingerprint,decision_json,response_json,status_code,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""", (response["request_id"], response["review_id"], response["actor"],
        response["action"], fingerprint, json.dumps(evidence), json.dumps(response), status, response["created_at"]))


def has_allocations(connection, order_id):
    return connection.execute("SELECT 1 FROM working_order WHERE order_id=? LIMIT 1", (order_id,)).fetchone() is not None


def create_order(connection, facts):
    connection.execute("""INSERT INTO orders
        (order_id,customer,product,category,pieces,order_date,due_date,source_status,state)
        VALUES (?,?,?,?,?,?,?,'READY','READY')""", tuple(facts[field] for field in ORDER_FIELDS))


def update_order(connection, facts, expected_version):
    cursor = connection.execute("""UPDATE orders SET customer=?,product=?,category=?,pieces=?,
        order_date=?,due_date=?,version=version+1 WHERE order_id=? AND version=?""",
        (*[facts[field] for field in EDITABLE_FIELDS], facts["order_id"], expected_version))
    if cursor.rowcount != 1:
        raise RuntimeError("Order changed inside the registration transaction.")


def history(connection, order_id, limit, offset):
    condition, args = (" WHERE order_id=?", (order_id,)) if order_id else ("", ())
    total = connection.execute("SELECT COUNT(*) FROM order_intake_reviews" + condition, args).fetchone()[0]
    rows = connection.execute("SELECT * FROM order_intake_reviews" + condition +
        " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
    return rows, total
