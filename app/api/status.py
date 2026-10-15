"""Map domain payloads to HTTP status codes."""


def session_status(payload):
    codes = payload.get("result", {}).get("reason_codes", [])
    if "INVALID_ARGUMENT" in codes:
        return 400
    if "SESSION_NOT_FOUND" in codes:
        return 404
    if "DB_ERROR" in codes:
        return 503
    if any(c in codes for c in (
            "IDEMPOTENCY_CONFLICT", "SESSION_VERSION_CONFLICT", "SESSION_CLOSED", "ORDER_VERSION_CONFLICT")):
        return 409
    return 200


def event_status(payload):
    codes = payload["result"]["reason_codes"]
    status = (400 if "INVALID_ARGUMENT" in codes else 404 if "ORDER_NOT_FOUND" in codes else
              503 if payload["result"]["decision_status"] == "ERROR" else
              409 if not payload["result"]["success"] else 200)
    if "IDEMPOTENCY_CONFLICT" in codes:
        status = 409
    return status


def request_status(payload):
    codes = payload["result"]["reason_codes"]
    if "IDEMPOTENCY_CONFLICT" in codes:
        return 409
    if "INVALID_ARGUMENT" in codes:
        return 400
    if payload["result"]["decision_status"] == "ERROR":
        return 503
    return 200


def job_error_status(error):
    code = error.get("error")
    if code in ("SESSION_NOT_FOUND", "JOB_NOT_FOUND"):
        return 404
    if code in ("SESSION_CLOSED", "IDEMPOTENCY_CONFLICT"):
        return 409
    if code in ("UNSUPPORTED_JOB_KIND", "INVALID_FIELDS", "INVALID_MESSAGE"):
        return 400
    return 400
