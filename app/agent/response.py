"""Deterministic response node; business types explicitly register their builders."""
from app.services.chat.presentation import build_allocation_response


RESPONSE_BUILDERS = {'allocation': build_allocation_response}


def assemble(state):
    result = state['task_result']
    builder = RESPONSE_BUILDERS.get(result['task_type'])
    if builder is None or state['source_node'] != result['task_type']:
        raise ValueError('UNSUPPORTED_RESPONSE_SOURCE')
    response = builder(result, state['explanation'])
    return {'response': response, 'reply': response['assistant_message']['content']}
