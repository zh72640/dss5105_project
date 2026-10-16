"""Bounded recent turns plus complete authoritative task facts and change sources."""
from app.db import context_repository


def build_context(connection, session):
    rows = context_repository.recent_messages(connection, session['session_id'])
    history, size = [], 0
    for row in rows:
        item = dict(row)
        if size + len(item['content']) > 18000:
            break
        history.append(item)
        size += len(item['content'])
    task = session['task']
    sequences = {source['message_sequence'] for source in task['sources'].values() if 'message_sequence' in source}
    sequences.update(change['sequence'] for change in task['changes'][-12:])
    for sequence in sorted(sequences):
        if sequence not in {m['sequence'] for m in history}:
            row = context_repository.message_at(connection, session['session_id'], sequence)
            if row and size+len(row['content'])<=18000:
                history.append(dict(row))
                size+=len(row['content'])
    return {'business_date': session['business_date'], 'history': sorted(history, key=lambda m:m['sequence']),
        'current_sequence': session['version'] * 2 + 1, 'draft': task['draft'], 'field_sources': task['sources'],
        'recent_changes': task['changes'][-12:], 'pending_questions': task['issues'],
        'order_facts': task['report'].get('resolved_fields', {}), 'recommendation': session['recommendation']}
