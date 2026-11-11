"""Deterministic, audited manual order registration and correction."""
import hashlib
import json
from uuid import uuid4

from app.db.database import Database, utc_now
from app.db import order_intake_repository as repo
from app.db.order_repository import get_order
from app.schemas.order_intake import EDITABLE_FIELDS, OrderReviewInput, OrderDecisionInput


class OrderIntakeError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code = status, code
        super().__init__(message)


def _actor(actor):
    if not isinstance(actor, str) or not actor.strip():
        raise OrderIntakeError(401, "LOGIN_REQUIRED", "Sign in to continue.")
    return actor


def _fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _owner(row, actor):
    if row is None or row["actor"] != actor:
        raise OrderIntakeError(404, "REVIEW_NOT_FOUND", "This review is unavailable for the signed-in user.")


def _replay(row, actor, fingerprint):
    if row["actor"] != actor or row["fingerprint"] != fingerprint:
        raise OrderIntakeError(409, "IDEMPOTENCY_CONFLICT", "This request ID was already used for a different request.")


def _blocker(connection, order):
    if order and (order["state"] not in {"READY", "UNASSIGNED"} or
                  order["completed_pieces"] or repo.has_allocations(connection, order["order_id"])):
        return "Only unstarted Ready or Unassigned orders can be corrected. Use production operations for active orders."
    return None


def _review_view(connection, row):
    return repo.review_snapshot(connection, row)


def check(data, *, actor, db_path):
    with Database(db_path) as db, db.transaction() as connection:
        return check_in_transaction(connection, data, actor=actor)


def check_in_transaction(connection, data, *, actor):
    """Compose registration and caller state in the same write transaction."""
    if not connection.in_transaction:
        raise RuntimeError("A write transaction is required.")
    actor = _actor(actor)
    body = OrderReviewInput.model_validate(data)
    proposed = body.order.model_dump()
    fingerprint = _fingerprint(data)
    saved = repo.review_by_request(connection, body.request_id)
    if saved:
        _replay(saved, actor, fingerprint)
        return {**_review_view(connection, saved), "replayed": True}
    existing = get_order(connection, proposed["order_id"])
    differences = [{"field": field, "stored": existing[field], "proposed": proposed[field]}
                   for field in EDITABLE_FIELDS if existing and existing[field] != proposed[field]]
    blocker = _blocker(connection, existing)
    review = {
        "review_id": str(uuid4()), "request_id": body.request_id, "actor": actor,
        "order_id": proposed["order_id"], "submitted": data["order"], "proposed": proposed,
        "existing": existing, "differences": differences,
        "match": "missing" if existing is None else "different" if differences else "identical",
        "expected_version": existing["version"] if existing else None,
        "can_update": existing is not None and blocker is None, "update_blocker": blocker,
        "created_at": utc_now(), "decision": None, "replayed": False,
    }
    repo.save_review(connection, review, fingerprint)
    return review


def get_review(review_id, *, actor, db_path):
    actor = _actor(actor)
    with Database(db_path) as db:
        row = repo.review_by_id(db.connection, review_id)
        _owner(row, actor)
        return _review_view(db.connection, row)


def decide(review_id, data, *, actor, db_path):
    with Database(db_path) as db, db.transaction() as connection:
        return decide_in_transaction(connection, review_id, data, actor=actor)


def decide_in_transaction(connection, review_id, data, *, actor):
    """Compose registration and caller state in the same write transaction."""
    if not connection.in_transaction:
        raise RuntimeError("A write transaction is required.")
    actor = _actor(actor)
    body = OrderDecisionInput.model_validate(data)
    fingerprint = _fingerprint({"review_id": review_id, **body.model_dump()})
    row = repo.review_by_id(connection, review_id)
    _owner(row, actor)
    saved = repo.decision_by_request(connection, body.request_id)
    if saved:
        _replay(saved, actor, fingerprint)
        return {**json.loads(saved["response_json"]), "replayed": True}, saved["status_code"]
    if repo.decision_by_review(connection, review_id):
        raise OrderIntakeError(409, "REVIEW_ALREADY_DECIDED", "This review has a recorded decision. Start a fresh check.")
    review = json.loads(row["review_json"])
    proposed = review["proposed"]
    current = get_order(connection, review["order_id"])
    before = current
    status, applied = 409, False
    fields = {item["field"] for item in review["differences"]}
    if body.action == "reject" and review["match"] != "identical":
        outcome, message, status = "REJECTED", "Decision recorded. The order was not changed.", 200
    elif review["match"] == "identical" or body.action != ("create" if review["match"] == "missing" else "update"):
        outcome, message = "INVALID_DECISION", "This action does not match the saved comparison. Start a fresh check."
    elif body.expected_version != review["expected_version"] or current != review["existing"]:
        outcome, message = "ORDER_CHANGED", "The order changed after this check. Review the latest facts before deciding again."
    elif body.action == "update" and (body.confirmed_order_id != review["order_id"] or
            set(body.verified_fields) != fields or len(body.verified_fields) != len(fields)):
        outcome, message = "VERIFICATION_REQUIRED", "Verify every changed field and retype the order ID before approving."
    elif body.action == "update" and _blocker(connection, current):
        outcome, message = "ORDER_UPDATE_BLOCKED", _blocker(connection, current)
    else:
        if body.action == "create":
            repo.create_order(connection, proposed)
            outcome, message = "CREATED", "New order confirmed and registered. It is ready for allocation in Chat."
        else:
            repo.update_order(connection, proposed, body.expected_version)
            outcome, message = "UPDATED", "Verified changes saved. Prepare a new allocation recommendation using the updated order."
        current = get_order(connection, review["order_id"])
        status, applied = 200, True
    response = {"request_id": body.request_id, "review_id": review_id, "action": body.action,
                "actor": actor, "reason": body.reason, "outcome": outcome, "applied": applied,
                "message": message, "order": current, "created_at": utc_now(), "replayed": False}
    evidence = {**body.model_dump(), "before": before, "after": current,
                "reviewed": review["existing"], "proposed": proposed, "differences": review["differences"]}
    repo.save_decision(connection, response, evidence, fingerprint, status)
    return response, status


def history(*, actor, db_path, order_id=None, limit=50, offset=0):
    _actor(actor)
    if not isinstance(limit, int) or not 1 <= limit <= 100 or not isinstance(offset, int) or offset < 0:
        raise ValueError("Invalid audit pagination.")
    with Database(db_path) as db:
        rows, total = repo.history(db.connection, order_id.strip().upper() if order_id else None, limit, offset)
        return {"items": [_review_view(db.connection, row) for row in rows], "total": total,
                "limit": limit, "offset": offset}
