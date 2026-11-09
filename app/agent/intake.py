"""Shared current-turn interpretation with evidence repair and request replay."""
import json

from app.db.database import Database
from app.db.chat_repository import snapshot
from app.db import agent_repository
from app.services.chat.context import build_context
from app.services.chat import extraction
from app.agent.dynamic import record_model_response, record_model_start
from app.llm.errors import check_response, check_structured, text_content, translate_error
from app.llm.json_output import json_text
from app.prompts import get_registry
from app.schemas.chat import AllocationExtraction

MAX_EXTRACTION_ATTEMPTS = 2


def _failed(code, message, task_id=""):
    return {"task_id": task_id, "task_type": "allocation", "status": "failed",
            "result": None, "issues": [{"code": code, "field": "workflow",
                                         "severity": "blocking", "question": message}]}


def interpret_current_message(context, *, prompt_id="allocation.extract", event_type="allocation_extraction"):
    """Interpret a current turn with bounded history, repair and durable replay.

    Allocation intake and follow-up resolution share the same evidence contract.
    Their prompts select semantics; the caller controls routing and execution.
    """
    with Database(context.db_path) as db:
        session = snapshot(db.connection, context.session_id, context.owner)
        if session is None:
            return {"task_result": _failed("SESSION_NOT_FOUND", "The session is unavailable.")}
        conversation = build_context(db.connection, session)
        saved = agent_repository.latest_extraction(db.connection, context.request_id, event_type)
    prompt = get_registry().snapshot(prompt_id,
        version=saved.get('prompt_version') if saved else None)
    variables = {"context": {"business_date": conversation['business_date'],
                 "task_id": session["task"]["task_id"], "task_state": session["task"]["state"],
                 "current_constraints": {k: conversation['draft'].get(k) for k in
                     ('order_id', 'objective', 'exclusion', 'preferred_workshop', 'deadline_required', 'num_workshop_allowed')},
                 "workshop_names": conversation.get('workshop_names', {}),
                 "pending_questions": conversation.get('pending_questions', []),
                 "history": conversation.get('history', [])[-12:],
                 "pending_alternatives": conversation.get('pending_alternatives', [])},
                 "output_schema": AllocationExtraction.model_json_schema()}
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    attempt = saved['attempt'] if saved else 1
    feedback = None
    while attempt <= MAX_EXTRACTION_ATTEMPTS:
        cached = saved is not None
        result = saved or _extract_once(context, model, spec, prompt, variables, attempt,
                                        feedback, conversation['current_sequence'], event_type)
        saved = None
        try:
            if result.get('parsing_error'):
                raise extraction.ExtractionValidationError('format', {
                    **extraction.format_details(ValueError('INVALID_EXTRACTION_FORMAT'),
                        result.get('extracted'), context.user_message, conversation['current_sequence']),
                    **result['parsing_error']})
            interpretation = extraction.validate_candidate(result.get('extracted'),
                message=context.user_message, conversation=conversation)
        except extraction.ExtractionValidationError as error:
            detail = {'attempt': attempt, 'stage': error.stage, **error.detail}
            if not cached or not result.get('validation_recorded'):
                _record_extraction_event(context, 'extraction_validation_failed' if event_type == 'allocation_extraction' else 'followup_validation_failed', detail)
            if attempt == MAX_EXTRACTION_ATTEMPTS:
                salvaged = extraction.salvage_due_date(result.get('extracted'), error,
                    message=context.user_message, conversation=conversation)
                if salvaged is not None:
                    return {"interpretation": salvaged.model_dump(),
                            "sequence": conversation["current_sequence"]}
                failure = _failed('EXTRACTION_FORMAT_INVALID' if error.stage == 'format' else
                    'EXTRACTION_EVIDENCE_INVALID', extraction.failure_message(error.stage, detail) +
                    extraction.recovery_hint(context.user_message, detail.get('field')),
                    session['task']['task_id'])
                failure['issues'][0].update(field=detail.get('field') or 'workflow',
                                           reason=detail['reason'], attempts=attempt)
                return {'task_result': failure}
            feedback = {'validation': detail, 'previous_output': result.get('raw_text'),
                        'previous_extraction': result.get('extracted')}
            attempt += 1
            continue
        return {"interpretation": interpretation.model_dump(),
                "sequence": conversation["current_sequence"]}


def _extract_once(context, model, spec, prompt, variables, attempt, feedback, sequence, event_type):
    bundle = prompt.render(variables=variables, user_message=context.user_message,
                           retry_feedback=json.dumps(feedback, ensure_ascii=False) if feedback else None)
    stage = "followup" if event_type == "followup_interpretation" else "extract"
    record_model_start(context, stage)
    try:
        if spec.output_method == "prompt":
            raw = model.invoke(bundle.as_messages())
            response = None
        else:
            response = model.with_structured_output(AllocationExtraction, method=spec.output_method,
                include_raw=True).invoke(bundle.as_messages())
            raw = response.get("raw") if isinstance(response, dict) else None
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    if raw is None:
        # Missing transport envelopes remain model errors, not extraction repairs.
        check_structured(response)
    record_model_response(context, stage, raw, bundle.metadata)
    check_response(raw, require_text=spec.output_method == 'prompt')
    text = text_content(raw)
    raw_calls = getattr(raw, 'tool_calls', []) or []
    invalid_calls = getattr(raw, 'invalid_tool_calls', []) or []
    parsing_error = None
    if spec.output_method == 'prompt':
        try:
            candidate = json.loads(json_text(text))
        except (ValueError, TypeError):
            candidate = None
            parsing_error = {'reason': 'INVALID_JSON',
                             'errors': [{'location': [], 'type': 'json_invalid'}]}
    else:
        candidate = response.get('parsed')
        structured_error = response.get('parsing_error')
        if hasattr(candidate, 'model_dump'):
            candidate = candidate.model_dump(mode='json')
        missing_parsed = candidate is None
        if candidate is None and text:
            # Recover output for diagnostics only; an SDK parse failure remains a failure.
            try:
                candidate = json.loads(json_text(text))
            except (ValueError, TypeError):
                pass
        if candidate is None and len(raw_calls) == 1:
            candidate = raw_calls[0].get('args')
        if candidate is None and len(invalid_calls) == 1:
            try:
                candidate = json.loads(invalid_calls[0].get('args', ''))
            except (ValueError, TypeError):
                pass
        if structured_error or missing_parsed:
            error = structured_error or ValueError('INVALID_EXTRACTION_FORMAT')
            parsing_error = extraction.format_details(error, candidate, context.user_message, sequence)
    result = {'contract': 'allocation_extraction_v1', 'attempt': attempt,
              'runtime_message_sequence': sequence, 'raw_tool_calls': raw_calls,
              'invalid_tool_calls': invalid_calls,
              'prompt_version': prompt.definition.version, 'raw_text': text,
              'extracted': candidate, 'parsing_error': parsing_error}
    _record_extraction_event(context, event_type, result)
    return result


def _record_extraction_event(context, kind, detail):
    """Persist extraction attempts and diagnostics in the existing owner-scoped trace."""
    with Database(context.db_path) as db, db.transaction() as connection:
        agent_repository.record_event(connection, session_id=context.session_id,
            request_id=context.request_id, event_type=kind, detail=detail)

