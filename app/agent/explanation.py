"""Explain a verified business result using a prompt selected by Runtime provenance."""
import json
import re

from app.agent.dynamic import AgentContext, record_model_response, record_model_start
from app.llm.errors import BackendError, check_response, text_content, translate_error
from app.prompts import get_registry
from app.schemas.agent import ExplanationInput
from app.services.chat.presentation import allocation_payload, issue_text
from app.services.chat.explanation_guard import claim_problem, fallback


EXPLANATION_PROMPTS = {('allocation', 'allocation'): 'allocation.explain'}


def _fallback(context, payload, reason):
    from app.db.database import Database
    from app.db import agent_repository
    with Database(context.db_path) as db, db.transaction() as connection:
        agent_repository.record_event(connection, session_id=context.session_id,
            request_id=context.request_id, event_type='explanation_fallback', detail={'reason': reason})
    return {'explanation': {'text': fallback(payload)}}


def explain(state, runtime):
    inputs: ExplanationInput = {'source_node': state['source_node'], 'task_result': state['task_result']}
    result = inputs['task_result']
    prompt_id = EXPLANATION_PROMPTS.get((inputs['source_node'], result['task_type']))
    if prompt_id is None:
        raise ValueError('UNSUPPORTED_EXPLANATION_SOURCE')
    if result['status'] in ('blocked', 'failed'):
        return {'explanation': {'text': issue_text(result)}}
    payload = allocation_payload(result)
    if payload is None:
        # A waiting executor pinned before this workflow may still have a question.
        return {'explanation': {'text': result['result']['question']}}
    context: AgentContext = runtime.context
    verified_result = {**result, 'result': payload}
    bundle = get_registry().render(prompt_id, variables={},
        user_message=json.dumps(verified_result, ensure_ascii=False, allow_nan=False))
    spec = context.registry.resolve('llm', context.model_key)
    model = context.registry.get_model('llm', context.model_key)
    record_model_start(context, "explanation")
    try:
        raw = model.invoke(bundle.as_messages())
    except Exception as error:
        translated = translate_error(error, spec.provider)
        if isinstance(translated, BackendError) and translated.retryable:
            return _fallback(context, payload, str(translated))
        raise translated from error
    record_model_response(context, 'explanation', raw, bundle.metadata)
    try:
        check_response(raw, require_text=False)
    except BackendError as error:
        if error.retryable:
            return _fallback(context, payload, str(error))
        raise
    if (getattr(raw, 'tool_calls', None) or getattr(raw, 'invalid_tool_calls', None) or
            (getattr(raw, 'additional_kwargs', {}) or {}).get('tool_calls')):
        raise BackendError('explanation_unexpected_tools', retryable=False)
    try:
        check_response(raw)
    except BackendError as error:
        if error.retryable:
            return _fallback(context, payload, str(error))
        raise
    text = text_content(raw).strip()
    if re.search(r'[\u4e00-\u9fff]', text):
        raise BackendError('explanation_not_english', retryable=False)
    problem = claim_problem(text, payload)
    if problem:
        return _fallback(context, payload, problem)
    return {'explanation': {'text': text}}
