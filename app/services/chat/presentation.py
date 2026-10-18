"""Pure response assembly and reconciliation with an authoritative session snapshot."""
from copy import deepcopy

from app.schemas.allocation import AllocationRecommendationResult
from app.schemas.chat import AllocationResponseBody
from app.schemas.agent import ExplanationResult, TaskResult
from app.services.allocation.contracts import saved_result


STALE_MESSAGE = "The recommendation became stale because business facts changed. Request a new calculation before confirmation."


def issue_text(result: TaskResult) -> str:
    from app.services.allocation.alternatives import issue_messages
    messages = issue_messages(result.get('issues', []))
    return ' '.join(messages) or 'The task could not be completed.'


def allocation_payload(result: TaskResult) -> dict | None:
    """Keep verified numbers intact, including results from pinned legacy executors."""
    if result['status'] in ('blocked', 'failed'):
        return None
    payload = result.get('result') or {}
    if payload.get('question'):
        return None
    if 'recommendation' in payload:
        return saved_result(payload['recommendation'])
    return AllocationRecommendationResult.model_validate(payload).model_dump()


def build_allocation_response(result: TaskResult, explanation: ExplanationResult) -> dict:
    """Package the explanation and original recommendation without computing facts."""
    if result['task_type'] != 'allocation':
        raise ValueError('ALLOCATION_RESPONSE_TYPE_MISMATCH')
    payload = allocation_payload(result)
    body = AllocationResponseBody(
        explanation=explanation['text'], allocation=payload, issues=deepcopy(result['issues']),
        recommendation_id=payload['recommendation_id'] if payload else None).model_dump()
    return {**body, 'assistant_message': {'role': 'assistant', 'content': body['explanation']}}


def reconcile_response(body: dict, session: dict) -> dict:
    """Suppress content that no longer matches the current valid saved recommendation."""
    if body.get('type') != 'allocation':
        raise ValueError('UNSUPPORTED_RESPONSE_TYPE')
    if body['allocation'] is None:
        return deepcopy(body)
    recommendation = session['recommendation']
    current = None
    if (recommendation and recommendation['status'] == 'valid' and
            recommendation['task_version'] == session['task']['task_version']):
        try:
            current = saved_result(recommendation)
        except (ValueError, KeyError, TypeError):
            pass
    if current == body['allocation']:
        return deepcopy(body)
    issue = {'code': 'RECOMMENDATION_STALE', 'field': 'recommendation',
             'severity': 'blocking', 'question': STALE_MESSAGE}
    return build_allocation_response({
        'task_id': session['task']['task_id'], 'task_type': 'allocation',
        'status': 'blocked', 'result': None, 'issues': [issue]}, {'text': STALE_MESSAGE})
