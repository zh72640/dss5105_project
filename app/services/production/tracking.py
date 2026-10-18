"""Evidence-backed presentation of the existing production lifecycle; no writes."""
import json


def build(order, records, completed_at):
    events, attempts = [], []
    for record in records:
        result = json.loads(record['decision_json'])
        response = json.loads(record['response_json'])
        action = record['action'] or 'allocate'
        applied = bool(record['applied']) if record['action'] else bool(result.get('success'))
        before = json.loads(record['before_json']) if record['before_json'] else {}
        after = json.loads(record['after_json']) if record['after_json'] else {}
        supplied = response.get('event') or {}
        delta = after.get('completed_pieces', 0) - before.get('completed_pieces', 0) if applied else 0
        entry = {
            'id': record['request_id'], 'action': action, 'applied': applied,
            'recorded_at': record['created_at'],
            'business_date': record['as_of_date'] or response.get('as_of_date'),
            'actor': record['actor'] or record['approval_actor'], 'reason': record['reason'],
            'completed_delta': max(0, delta), 'workshop_id': supplied.get('workshop_id'),
            'completed_total': after.get('completed_pieces'),
            'state_before': before.get('state'), 'state_after': after.get('state') or ('WORKING' if applied else None),
            'allocation': [{'workshop_id': part['workshop_id'], 'pieces': part['pieces']}
                           for part in result.get('allocation', [])] if applied else [],
            'reason_codes': result.get('reason_codes', []),
        }
        (events if applied else attempts).append(entry)

    state, completed = order['state'], order['completed_pieces']
    allocation_evidence = bool(order['allocations']) or any(e['action'] in ('allocate', 'reassign') for e in events)
    production_evidence = any(e['completed_delta'] > 0 for e in events)
    if state == 'COMPLETED':
        current = 'completed'
        statuses = ['done', 'done' if allocation_evidence else 'unknown',
                    'done' if production_evidence else 'unknown', 'current']
    elif state == 'LAPSED':
        current = 'lapsed'
        statuses = ['done', 'past' if allocation_evidence else 'blocked',
                    'past' if production_evidence else 'blocked', 'blocked']
    elif state == 'WORKING':
        current = 'production' if production_evidence or completed else 'allocated'
        statuses = ['done', 'done' if current == 'production' else 'current',
                    'current' if current == 'production' else 'pending', 'pending']
    else:
        current = 'awaiting_allocation'
        statuses = ['done', 'current', 'paused' if completed else 'pending', 'pending']
    return {
        'current': current, 'completed_pieces': completed, 'total_pieces': order['pieces'],
        'progress_percent': round(100 * completed / order['pieces'], 2),
        'stages': [{'key': key, 'label': label, 'status': status} for (key, label), status in zip(
            [('registered', 'Registered'), ('allocated', 'Allocation'), ('production', 'Production'),
             ('completed', 'Completed')], statuses)],
        'registered_date': order['order_date'], 'completed_at': completed_at,
        'events': events, 'attempts': attempts,
        'history_note': ('Earlier allocation and production milestones were not recorded in this workspace.'
                         if state == 'COMPLETED' and not production_evidence else None),
    }
