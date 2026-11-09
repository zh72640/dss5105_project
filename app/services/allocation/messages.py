"""Readable allocation feedback; internal reason codes remain available for audit."""
import re

from app.schemas.business import Workshop


def eligibility_reason_text(reason: str) -> str:
    """Describe a recorded rejection as an English clause without exposing its code.

    Accept allocator codes in either case, including quantity-specific batch caps.
    Unknown codes receive a neutral explanation instead of guessed business facts.
    """
    code = reason.lower()
    descriptions = {
        'excluded_by_user': 'you excluded it from this request',
        'cannot_make_tops': 'it cannot make tops',
        'cannot_make_accessories': 'it cannot make accessories',
        'status_suspended': 'it is currently suspended',
        'status_closed': 'it is closed',
        'status_inactive': 'it is not currently active',
        'invalid_capacity_or_queue': 'its capacity or queue data is invalid',
        'unknown_workshop': 'it is not registered',
    }
    if code in descriptions:
        return descriptions[code]
    limit = re.fullmatch(r'exceeds_(\d+)_piece_limit', code)
    if limit:
        return f'this batch exceeds its limit of {int(limit[1]):,} pieces'
    if code.startswith('status_'):
        return 'it is not currently active'
    if code.startswith('cannot_make_'):
        return 'it does not support this product category'
    return 'it does not meet the requirements for this order'


def workshop_refusal(workshop: Workshop, reason: str) -> str:
    """Name the checked workshop and explain its recorded eligibility failure."""
    return (f'{workshop.name} ({workshop.workshop_id}) cannot handle this order because '
            f'{eligibility_reason_text(reason)}.')


def planning_failure_text(code: str) -> str:
    """Explain a failed allocation while leaving its structured reason code intact."""
    descriptions = {
        'NO_ELIGIBLE_WORKSHOP': 'No workshop meets the current eligibility requirements.',
        'DEADLINE_INFEASIBLE': 'No feasible allocation can meet the required delivery date.',
        'CAPACITY_INFEASIBLE': 'The full order cannot fit within the current batch-size and workshop-count limits.',
        'WEIGHTED_HYBRID_SINGLE_WORKSHOP_ONLY':
            'Normalized 80/20 scoring supports one workshop. Choose one workshop or another objective for splitting.',
    }
    if code.upper() in descriptions:
        return descriptions[code.upper()]
    if code.lower().startswith(('status_', 'cannot_make_', 'exceeds_')) or code.lower() in (
            'excluded_by_user', 'unknown_workshop', 'invalid_capacity_or_queue'):
        return f'The requested workshop cannot handle this order because {eligibility_reason_text(code)}.'
    return 'No feasible allocation satisfies the current requirements. Review the workshop, batch size and delivery constraints.'


INPUT_MISSING_CODES = frozenset({'REQUIRED_INFO_INCOMPLETE', 'SKILL_INPUT_INCOMPLETE'})
FIELD_LABELS = {'order_id': 'order number', 'product': 'product type', 'pieces': 'quantity',
                'customer': 'customer', 'category': 'product category',
                'order_date': 'order date', 'due_date': 'due date'}
ORDER_ID_EXAMPLE_REQUEST = 'Provide the order ID, such as ORD-045.'


def clarification_questions(issues):
    """Humanize missing-information diagnostics while retaining detailed clarifications.

    List only reported missing fields, never a fixed bundle of required fields.
    Emit one summary of those fields before the original model questions
    and business explanations. Remove only the fixed trailing order-ID example
    from MISSING_ORDER_ID messages; never shorten the model's clarification or
    modify structured issues, blockers, or audit data.
    """
    missing = set()
    for problem in issues:
        if problem.get('code') in INPUT_MISSING_CODES:
            missing.update(problem.get('missing_fields') or [problem.get('field')])
        if problem.get('code') == 'MISSING_ORDER_ID':
            missing.add('order_id')
    messages = []
    if missing:
        labels = [label for field, label in FIELD_LABELS.items() if field in missing]
        if labels:
            detail = labels[0] if len(labels) == 1 else (
                ' and '.join(labels) if len(labels) == 2 else ', '.join(labels[:-1]) + ', and ' + labels[-1])
            messages.append(f"I don't yet have the {detail} needed to prepare an allocation recommendation.")
        else:
            messages.append("I don't yet have all the order details needed to prepare an allocation recommendation.")
    for problem in issues:
        if problem.get('code') in INPUT_MISSING_CODES:
            continue
        text = (problem.get('question') or '').strip()
        if problem.get('code') == 'MISSING_ORDER_ID':
            # Trim the known template suffix only. Similar wording authored by
            # the model belongs to its explanation and must remain intact.
            if text.endswith(ORDER_ID_EXAMPLE_REQUEST):
                text = text[:-len(ORDER_ID_EXAMPLE_REQUEST)].rstrip()
        if text:
            messages.append(text)
    return list(dict.fromkeys(messages))
