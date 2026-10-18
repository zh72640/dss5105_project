"""Collect input blockers before planning; validate the complete computed solution."""
import hashlib
import json
import math
from dataclasses import asdict
from datetime import date
from app.schemas.parser_schema import OBJECTIVES, ParseResult
from app.db.workshop_repository import get_all
from app.db.order_repository import get_order
from app.allocator import exclusion_reason


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def issue(code, field, question, user_value=None, database_value=None, source=None):
    return dict(code=code, field=field, severity='blocking', question=question,
        user_value=user_value, database_value=database_value, source=source)


def preflight(connection, draft, as_of, pending=(), sources=None):
    problems = list(pending)
    order = None
    workshops = []
    constraints = {key: draft.get(key) for key in ('objective', 'exclusion', 'num_workshop_allowed',
        'preferred_workshop', 'deadline_required')}
    constraints['objective'] = constraints['objective'] or 'min_delay'
    constraints['num_workshop_allowed'] = constraints['num_workshop_allowed'] or 1
    constraints['exclusion'] = constraints['exclusion'] or []
    constraints['deadline_required'] = bool(constraints['deadline_required'])
    report = dict(ready_for_planning=False, ready_for_recommendation=False, blocking_issues=problems,
        warnings=[], resolved_fields={}, effective_constraints=constraints, sources=sources or {},
        defaults={key: value for key, value in constraints.items() if key not in (sources or {})},
        business_date=as_of.isoformat())
    if not draft.get('order_id'):
        problems.append(issue('MISSING_ORDER_ID', 'order_id', 'Provide the order ID to allocate, such as ORD-045.'))
    else:
        row = get_order(connection, draft['order_id'])
        if row is None:
            problems.append(issue('ORDER_NOT_FOUND', 'order_id', 'Order not found. Check the order ID.', draft['order_id']))
        else:
            order = row
            report['resolved_fields'] = order
            if order['state'] not in ('READY', 'UNASSIGNED'):
                problems.append(issue('ORDER_ALREADY_' + order['state'], 'order_id',
                    'Order state is ' + order['state'] + '. It cannot be allocated again; use production management for reassignment.'))
            for field in ('customer', 'product', 'category', 'pieces', 'order_date', 'due_date'):
                if draft.get(field) is not None and str(draft[field]).casefold() != str(order[field]).casefold():
                    problems.append(issue('ORDER_FIELD_CONFLICT', field,
                        f'{field} conflicts with the registered order: supplied {draft[field]}, registered {order[field]}. Use the registered value or correct the order record.',
                        draft[field], order[field], (sources or {}).get(field)))
                if order[field] is None or (isinstance(order[field], str) and not order[field].strip()):
                    problems.append(issue('ORDER_DATA_MISSING', field, f'The registered order lacks {field}. Correct the order record first.'))
            if order['category'] not in ('TOPS', 'ACCESSORIES'):
                problems.append(issue('INVALID_CATEGORY', 'category', 'The registered category is unsupported. Correct the order record.'))
            if (type(order['pieces']) is not int or type(order['completed_pieces']) is not int or
                    not 0 <= order['completed_pieces'] < order['pieces']):
                problems.append(issue('INVALID_REMAINING_PIECES', 'pieces', 'Remaining pieces must be a positive integer.'))
            try:
                if date.fromisoformat(order['due_date']) < date.fromisoformat(order['order_date']):
                    problems.append(issue('INVALID_ORDER_DATES', 'due_date', 'The due date precedes the order date.'))
            except (ValueError, TypeError):
                problems.append(issue('INVALID_ORDER_DATES', 'due_date', 'The registered order dates are invalid.'))
    if constraints['objective'] not in OBJECTIVES:
        problems.append(issue('INVALID_OBJECTIVE', 'objective', 'Choose speed, cost, defect rate, or the weighted time and quality objective.'))
    limit = constraints['num_workshop_allowed']
    if type(limit) is not int or not 1 <= limit <= 8:
        problems.append(issue('INVALID_WORKSHOP_LIMIT', 'num_workshop_allowed', 'The workshop limit must be an integer from 1 to 8.'))
    if constraints['preferred_workshop'] in constraints['exclusion']:
        problems.append(issue('PREFERRED_EXCLUDED', 'preferred_workshop', 'The same workshop is preferred and excluded. Clarify which constraint applies.'))
    try:
        workshops = get_all(connection, as_of)
        ids = {w.workshop_id for w in workshops}
        for wid in set(constraints['exclusion']) | ({constraints['preferred_workshop']} if constraints['preferred_workshop'] else set()):
            if wid not in ids:
                problems.append(issue('UNKNOWN_WORKSHOP', 'workshop', f'Workshop {wid} was not found. Correct or remove that constraint.', wid))
        for w in workshops:
            numbers = (w.capacity, w.lead_days, w.cost, w.defect_rate, w.queue_days)
            if (not all(isinstance(n, (int, float)) and math.isfinite(n) for n in numbers) or
                    w.capacity <= 0 or min(w.lead_days, w.cost, w.queue_days) < 0 or not 0 <= w.defect_rate <= 1 or
                    (w.max_batch is not None and (type(w.max_batch) is not int or w.max_batch <= 0))):
                problems.append(issue('INVALID_RESOURCE_DATA', 'workshop', f'Workshop {w.workshop_id} has invalid capacity, queue, cost, or quality data.'))
        preferred = next((w for w in workshops if w.workshop_id == constraints['preferred_workshop']), None)
        if preferred and order and type(order['pieces']) is int:
            reason = exclusion_reason(preferred, order['category'], order['pieces'] - order['completed_pieces'], constraints['exclusion'])
            if reason:
                problems.append(issue('PREFERRED_INELIGIBLE', 'preferred_workshop', f'Required sole workshop {preferred.workshop_id} cannot take the full batch: {reason}.'))
    except (ValueError, TypeError):
        problems.append(issue('RESOURCE_DATA_ERROR', 'workshop', 'Workshop queue data is missing or the business date is invalid.'))
    report['blocking_issues'] = list({(p['code'], p['field'], p['question']): p for p in problems}.values())
    report['ready_for_planning'] = not report['blocking_issues']
    if not report['ready_for_planning']:
        from app.services.allocation.alternatives import attach
        planned_limit = limit if sources is not None and 'num_workshop_allowed' in sources else 1
        attach(report, order, workshops, as_of, max_workshops=planned_limit)
    facts_hash = None
    if report['ready_for_planning']:
        facts_hash = digest({'order': order, 'constraints': constraints, 'business_date': as_of.isoformat(),
            'workshops': [{**asdict(w), 'makes': sorted(w.makes)} for w in workshops]})
    return report, order, workshops, facts_hash


def check_solution(result, order, workshops, draft, report, as_of):
    if not result['success']:
        for code in result['reason_codes']:
            report['blocking_issues'].append(issue(code, 'constraints', 'No feasible plan satisfies the current constraints: ' + code + '. Revise the relevant constraint.'))
        from app.services.allocation.alternatives import attach
        attach(report, order, workshops, as_of, max_workshops=report.get('planning_max_workshops', 1))
        return report
    constraints = report['effective_constraints']
    parts = result['allocation']
    known = {w.workshop_id: w for w in workshops}
    planned_limit = report.get('planning_max_workshops', constraints['num_workshop_allowed'])
    valid = (bool(parts) and len({p['workshop_id'] for p in parts}) == len(parts) and
        len(parts) <= planned_limit and
        all(type(p['pieces']) is int and p['pieces'] > 0 for p in parts) and
        sum(p['pieces'] for p in parts) == order['pieces'] - order['completed_pieces'])
    for p in parts:
        w = known.get(p['workshop_id'])
        valid = valid and w is not None and exclusion_reason(w, order['category'], p['pieces'], constraints['exclusion']) is None
    if constraints['preferred_workshop']:
        valid = valid and len(parts) == 1 and parts[0]['workshop_id'] == constraints['preferred_workshop']
    if constraints['deadline_required']:
        valid = valid and result['deadline_met'] and date.fromisoformat(result['estimated_delivery_date']) <= date.fromisoformat(order['due_date'])
    if not valid:
        report['blocking_issues'].append(issue('INVALID_SOLUTION', 'allocation', 'The plan failed quantity or hard-constraint validation and cannot be recommended.'))
    report['warnings'] = result.get('warnings', [])
    report['ready_for_recommendation'] = not report['blocking_issues']
    return report
