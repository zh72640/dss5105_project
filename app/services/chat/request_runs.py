"""Explicitly end interrupted requests without removing their history or business results."""
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from app.db import agent_repository, chat_repository
from app.db.database import Database, utc_now
from app.services.chat.service import ChatError, require_session


# The local server runs one worker. Hold a claim across model calls and all writes,
# including production transactions, so ending cannot race a late tool result.
_claim_lock = Lock()
_executing = set()


@contextmanager
def execution_claim(db_path, session_id):
    key = (str(Path(db_path).resolve()).casefold(), session_id)
    with _claim_lock:
        if key in _executing:
            raise ChatError("REQUEST_EXECUTING", "This request is still executing. Wait for it to finish before retrying or ending it.")
        _executing.add(key)
    try:
        yield
    finally:
        with _claim_lock:
            _executing.remove(key)


def end_request(sid, *, request_id, expected_version, owner, db_path):
    # Check ownership before reporting whether a session is executing.
    with Database(db_path) as db:
        require_session(db.connection, sid, owner)
    with execution_claim(db_path, sid):
        with Database(db_path) as db:
            with db.transaction() as connection:
                session = require_session(connection, sid, owner)
                row = agent_repository.run(connection, request_id)
                if row is None or row["session_id"] != sid:
                    raise ChatError("REQUEST_NOT_FOUND", "The request does not exist in this session.", 404)
                if row["base_version"] != expected_version:
                    raise ChatError("SESSION_VERSION_CONFLICT", "Refresh the session and retry.")
                ended = agent_repository.ended_request(connection, request_id)
                if ended:
                    return {**ended, "replayed": True}
                if row["status"] == "finished":
                    return {"session_id": sid, "request_id": request_id, "ended": False,
                            "session_version": session["version"], "replayed": False,
                            "message": "This request has already finished. Its results are available in the session."}
                if session["status"] != "OPEN" or session["version"] != expected_version:
                    raise ChatError("SESSION_VERSION_CONFLICT", "Refresh the session and retry.")
                active = agent_repository.running_request(connection, sid)
                if active and active["request_id"] != request_id:
                    raise ChatError("AGENT_RUN_IN_PROGRESS", "Another request is pending in this session.")
                agent_repository.set_run_status(connection, request_id, "failed")
                chat_repository.increment_session(connection, sid, utc_now())
                response = {"session_id": sid, "request_id": request_id, "ended": True,
                            "session_version": expected_version + 1, "replayed": False,
                            "message": "Request ended. Saved recommendations and business records have been kept. You can send a new message."}
                agent_repository.record_event(connection, session_id=sid, request_id=request_id,
                    event_type="request_ended", detail=response)
                return response
