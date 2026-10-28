"""Durable per-session Agent turns; business writes remain in guarded tools."""
from datetime import date
import json
import uuid


from app.agent.dynamic import AgentContext, final_text
from app.agent.runtime import RunInProgress, run as run_runtime
from app.agent import skills
from app.llm.errors import BackendError, ModelSelectionError
from app.db.database import Database, utc_now
from app.services.allocation.preflight import digest
from app.services.chat.completion import _verified_reply
from app.services.chat.presentation import reconcile_response
from app.db import agent_repository


def _event(connection, sid, request_id, kind, detail):
    agent_repository.record_event(connection, session_id=sid, request_id=request_id,
                                  event_type=kind, detail=detail)


def turn(sid, *, owner, request_id, expected_version, db_path, message, registry):
    from app.services.chat.request_runs import execution_claim
    from app.services.chat.service import require_session
    with Database(db_path) as db:
        require_session(db.connection, sid, owner)
    with execution_claim(db_path, sid):
        return _turn(sid, owner=owner, request_id=request_id, expected_version=expected_version,
                     db_path=db_path, message=message, registry=registry)


def _turn(sid, *, owner, request_id, expected_version, db_path, message, registry):
    from app.services.chat.service import ChatError, encoded, replay, require_session, reconcile_recommendation

    if not message.strip():
        raise ChatError("INVALID_MESSAGE", "Enter a message.", 400)
    fingerprint = digest([sid, owner, request_id, expected_version, "message", message, None])
    with Database(db_path) as db:
        with db.transaction() as connection:
            cached = replay(connection, request_id, fingerprint, owner)
            if cached:
                return cached
            session = require_session(connection, sid, owner)
            row = agent_repository.run(connection, request_id)
            if row and (row["session_id"] != sid or row["fingerprint"] != fingerprint):
                raise ChatError("IDEMPOTENCY_CONFLICT", "This request ID was used for different input.")
            ended = agent_repository.ended_request(connection, request_id)
            if ended:
                raise ChatError("REQUEST_ENDED", "This request was ended. Send a new message with a new request ID.")
            scope = agent_repository.execution_scope(connection, sid)
            if session["status"] != "OPEN" or session["version"] != expected_version:
                raise ChatError("SESSION_VERSION_CONFLICT", "Refresh the session and retry.")
            active = agent_repository.running_request(connection, sid)
            if active and active["request_id"] != request_id:
                previous = agent_repository.run(connection, active["request_id"])
                raise ChatError("AGENT_RUN_IN_PROGRESS", "End the interrupted request before starting another turn.",
                    details={"session_id": sid, "request_id": previous["request_id"],
                             "expected_version": previous["base_version"], "can_end": True,
                             "retryable": False})
            if row:
                _event(connection, sid, request_id, "resume", {"session_version": expected_version})
            else:
                agent_repository.start_run(connection, request_id, sid, fingerprint, expected_version)
                _event(connection, sid, request_id, "start", {"session_version": expected_version,
                       "task_id": session["task"]["task_id"], "task_version": session["task"]["task_version"]})
            business_date = date.fromisoformat(session["business_date"])
            model_key = session["model_key"]

    context = AgentContext(registry, model_key, owner, db_path, sid, request_id, message, business_date,
                           skill_root=skills.SKILL_ROOT, execution_scope=scope)
    try:
        state = run_runtime(context, registry)
    except Exception as error:
        with Database(db_path) as db:
            with db.transaction() as connection:
                phase = agent_repository.latest_model_stage(connection, request_id)
                detail = {"type": type(error).__name__, "phase": phase,
                    "code": error.code if isinstance(error, ModelSelectionError) else
                            str(error) if isinstance(error, BackendError) else None,
                    "retryable": error.retryable if isinstance(error, BackendError) else False}
                if isinstance(error, BackendError):
                    detail.update(error.details())
                _event(connection, sid, request_id, "execution_error", detail)
                if isinstance(error, ModelSelectionError) and error.code == "TOOLS_UNSUPPORTED":
                    agent_repository.set_run_status(connection, request_id, "failed")
        details = {"session_id": sid, "request_id": request_id, "expected_version": expected_version,
                   "phase": phase, "can_end": True, "retryable": False}
        if isinstance(error, ModelSelectionError):
            raise ChatError(error.code, str(error), error.status, details=details) from None
        if isinstance(error, BackendError):
            details.update(retryable=error.retryable, model_error=error.details())
            code = "MODEL_UNAVAILABLE" if error.retryable else "MODEL_REQUEST_FAILED"
            raise ChatError(code, error.user_message(), 503 if error.retryable else 502, details=details) from None
        if isinstance(error, RunInProgress):
            raise ChatError("AGENT_RUN_IN_PROGRESS", str(error)) from None
        raise

    reply = (state.get("reply") or final_text(state)).strip() or "Please continue in this session."
    with Database(db_path) as db:
        with db.transaction() as connection:
            cached = replay(connection, request_id, fingerprint, owner)
            if cached:
                return cached
            session = require_session(connection, sid, owner)
            if session["version"] != expected_version or session["status"] != "OPEN":
                raise ChatError("SESSION_VERSION_CONFLICT", "Refresh the session and retry.")
            stale = reconcile_recommendation(connection, session)
            if stale:
                reply = "The previous recommendation became stale because business facts changed. Please request a new calculation."
                session = require_session(connection, sid, owner)
            task = session["task"]
            rec = session["recommendation"]
            body = state.get('response')
            if body is not None:
                body = reconcile_response(body, session)
                reply = body['explanation']
            reply = _verified_reply(reply, state, task, rec)
            if body is not None:
                body['explanation'] = reply
            visible_rec_id = (body['recommendation_id'] if body is not None else
                              rec['recommendation_id'] if rec and rec['status'] == 'valid' else None)
            turn_id, feedback_id = uuid.uuid4().hex, uuid.uuid4().hex
            now = utc_now()
            sequence = expected_version * 2
            telemetry = {"workflow": state.get("workflow_version", "dynamic_agent_v1"), "loaded_skills": [
                {"name": item["name"], "hash": item["hash"]} for item in state.get("loaded_skills", {}).values()],
                "tool_calls": len(state.get("tool_results", [])), "pending_question": state.get("pending_question")}
            telemetry.update(agent_repository.model_usage(connection, request_id))
            agent_repository.record_turn_start(connection, turn_id=turn_id, session_id=sid,
                request_id=request_id, fingerprint=fingerprint, base_version=expected_version,
                input_json=encoded({"message": message}), telemetry_json=encoded(telemetry))
            agent_repository.record_message_pair(connection, session_id=sid, turn_id=turn_id,
                sequence=sequence, user_message=message, assistant_message=reply,
                feedback_id=feedback_id, recommendation_id=(visible_rec_id if body is not None else
                    rec['recommendation_id'] if rec else None),
                workflow=state.get("workflow_version", "dynamic_agent_v1"))
            response = {**(body or {}), "session_id": sid, "session_version": expected_version + 1, "turn_id": turn_id,
                        "intent": "agent", "task_state": task["state"], "validation_report": task["report"],
                        "assistant_message": {"message_id": feedback_id, "content": reply, "role": "assistant"},
                        "feedback_message_id": feedback_id,
                        "recommendation_id": visible_rec_id,
                        "cards": [rec] if visible_rec_id else [],
                        "suggested_actions": [], "committed": False, "replayed": False, "http_status": 200,
                        "pending_question": (state.get("pending_question") or
                            (state.get("task_result") or {}).get("result", {}).get("question") if
                            isinstance((state.get("task_result") or {}).get("result"), dict) else None)}
            response["session"] = require_session(connection, sid, owner)
            agent_repository.finalize_turn(connection, turn_id, encoded(response), request_id)
            _event(connection, sid, request_id, "finish" if not state.get("pending_question") else "wait_user",
                   {"state": task["state"], "recommendation_id": response["recommendation_id"],
                    "session_version": expected_version + 1, "question": state.get("pending_question")})
            return response
