"""Resolve contextual follow-ups before choosing a business workflow."""
from app.agent.intake import interpret_current_message
from app.services.chat import service as chat


ALLOCATION_INTENTS = frozenset({'allocate_request', 'modify_constraints',
                               'answer_clarification', 'undo_change', 'select_workshop'})


def resolve(state, runtime):
    """Use the LLM's grounded interpretation, without changing business state.

    Accepted saved options and explicit revisions enter allocation with the same
    validated interpretation. Explanations use the read-only compatibility loop;
    unresolved references ask a dialogue question without persisting a task blocker.
    """
    output = interpret_current_message(runtime.context, prompt_id='agent.followup',
                                       event_type='followup_interpretation')
    if output.get('task_result'):
        result = output['task_result']
        return {'followup_route': 'finish', 'task_result': result,
                'reply': ' '.join(p['question'] for p in result['issues'])}
    interpretation = output['interpretation']
    if interpretation['intent'] == 'request_alternatives':
        return {'followup_route': 'alternatives'}
    if interpretation.get('accept_alternative') or interpretation['intent'] in ALLOCATION_INTENTS:
        return {'followup_route': 'allocation',
                'followup_interpretation': interpretation,
                'followup_sequence': output['sequence']}
    if interpretation['intent'] == 'unsupported_or_ambiguous':
        question = interpretation.get('ambiguity_reason') or 'Which option or requirement do you mean?'
        context = runtime.context
        session = chat.inspect(context.session_id, owner=context.owner, db_path=context.db_path)
        return {'followup_route': 'finish', 'reply': question, 'pending_question': question,
                'task_result': {'task_id': session['task']['task_id'], 'task_type': 'followup',
                                'status': 'waiting_user', 'result': {'question': question}, 'issues': []}}
    return {'followup_route': 'compat', 'compat_task_type': (
        'followup_readonly' if interpretation['intent'] in (
            'explain_recommendation', 'query_order', 'query_workshop') else 'compat')}


def alternatives(state, runtime):
    """Invoke the deterministic preview Service after LLM follow-up interpretation."""
    from app.services.chat.candidate_options import prepare
    context = runtime.context
    result = prepare(db_path=context.db_path, session_id=context.session_id, owner=context.owner,
                     request_id=context.request_id, as_of=context.as_of)
    return {'task_result': result, 'source_node': 'allocation'}
