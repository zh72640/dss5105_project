"""Explain a verified business result using a prompt selected by Runtime provenance."""
import json
import re

from app.agent.dynamic import AgentContext, record_model_response, record_model_start
from app.llm.errors import BackendError, check_response, text_content, translate_error
from app.prompts import get_registry
from app.schemas.agent import ExplanationInput
from app.services.chat.presentation import allocation_payload, issue_text


EXPLANATION_PROMPTS = {('allocation', 'allocation'): 'allocation.explain'}


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
        raise translate_error(error, spec.provider) from error
    record_model_response(context, 'explanation', raw, bundle.metadata)
    check_response(raw, require_text=False)
    if (getattr(raw, 'tool_calls', None) or getattr(raw, 'invalid_tool_calls', None) or
            (getattr(raw, 'additional_kwargs', {}) or {}).get('tool_calls')):
        raise BackendError('explanation_unexpected_tools', retryable=False)
    check_response(raw)
    text = text_content(raw).strip()
    if re.search(r'[\u4e00-\u9fff]', text):
        raise BackendError('explanation_not_english', retryable=False)
    return {'explanation': {'text': text}}
