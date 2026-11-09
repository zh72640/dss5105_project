"""Conservative claim checks and a factual fallback; no allocation calculations.

These checks catch unsupported identifiers, dates, numbers and explicit contradictions.
They are not a general proof of natural-language correctness.
"""
import json
import re
from datetime import date

METHODS = {
    'min_delay': 'earliest completion among the evaluated feasible plans',
    'min_cost': 'lowest production cost among the evaluated feasible plans',
    'min_defects': 'lowest expected defect rate among the evaluated feasible plans',
    'hybrid': 'the recorded time and quality score',
    'weighted_hybrid': 'the normalized score: 80% signed lateness and 20% defect exposure',
}
NUMBER = re.compile(r'(?<![\w-])-?\d+(?:,\d{3})*(?:\.\d+)?(?:%)?(?![\w-])')
IDENTIFIER = re.compile(r'\b(?:ORD-\d+|W\d+)\b', re.I)

MONTH_NAMES = ('january', 'february', 'march', 'april', 'may', 'june',
               'july', 'august', 'september', 'october', 'november', 'december')
MONTH_NUMBERS = {name: number for number, name in enumerate(MONTH_NAMES, 1)}
MONTH_NUMBERS.update({name[:3]: number for number, name in enumerate(MONTH_NAMES, 1)})
MONTH_NUMBERS['sept'] = 9
MONTH_PATTERN = '(?:' + '|'.join(sorted(MONTH_NUMBERS, key=len, reverse=True)) + r')\.?'
ISO_DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
DATE_CLAIM = re.compile(
    r'\b(?:(?P<iso>\d{4}-\d{2}-\d{2})|'
    rf'(?P<month_first>{MONTH_PATTERN})\s+(?P<day_last>\d{{1,2}})(?:st|nd|rd|th)?'
    r'(?:,?\s+(?P<year_last>\d{4}))?|'
    rf'(?P<day_first>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month_last>{MONTH_PATTERN})'
    r'(?:,?\s+(?P<year_first>\d{4}))?)\b', re.I)


def _date_claim_value(match, recorded_dates):
    """Normalize a date mention; yearless dates require one matching saved date.

    Calendar validation rejects impossible dates. No business-year or locale
    assumptions are used to complete a model-generated date.
    """
    if match['iso']:
        return date.fromisoformat(match['iso']).isoformat()
    month = MONTH_NUMBERS[(match['month_first'] or match['month_last']).lower().rstrip('.')]
    day = int(match['day_last'] or match['day_first'])
    year = match['year_last'] or match['year_first']
    if year:
        return date(int(year), month, day).isoformat()
    matches = {value for value in recorded_dates if value[5:] == f'{month:02d}-{day:02d}'}
    if len(matches) != 1:
        raise ValueError('The yearless date is absent or ambiguous in the saved recommendation.')
    return matches.pop()


def claim_problem(text, payload):
    """Return the first fact-check failure code, or None for a supported explanation.

    Dates are compared by calendar value against the saved payload before other
    numbers are checked. Neither the explanation text nor the payload is changed.
    """
    evidence = json.dumps(payload, ensure_ascii=False)
    if set(IDENTIFIER.findall(text.upper())) - set(IDENTIFIER.findall(evidence.upper())):
        return 'unsupported_identifier'
    numbers = set()

    def collect(value, key=''):
        if isinstance(value, dict):
            for name, child in value.items():
                if name not in ('recommendation_id', 'task_version', 'resolved_differences'):
                    collect(child, name)
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif type(value) in (int, float):
            numbers.add(float(value))
            numbers.add(round(float(value), 2))
            if key == 'delay_days':
                numbers.add(abs(float(value)))
            if 'rate' in key:
                numbers.add(round(float(value) * 100, 2))
        elif isinstance(value, str):
            numbers.update(float(v.replace(',', '').rstrip('%')) for v in NUMBER.findall(value))

    collect(payload)
    if payload['objective'] == 'weighted_hybrid':
        numbers.update((80., 20.))
    # Dates and IDs are checked separately; punctuation is not a numeric claim.
    recorded_dates = set(ISO_DATE.findall(evidence))
    try:
        if any(_date_claim_value(match, recorded_dates) not in recorded_dates
               for match in DATE_CLAIM.finditer(text)):
            return 'unsupported_date'
    except ValueError:
        return 'unsupported_date'
    # Remove only checked date spans, so their day/year do not become ordinary
    # number claims. Standalone numbers still go through the original check.
    prose = IDENTIFIER.sub('', DATE_CLAIM.sub(' ', text))
    if any(float(v.replace(',', '').rstrip('%')) not in numbers for v in NUMBER.findall(prose)):
        return 'unsupported_number'
    if re.search(r'\b(?:we guarantee|guaranteed (?:delivery|quality|completion))\b', text, re.I):
        return 'unverified_guarantee'
    if payload.get('due_date') is None and re.search(r'\b(?:meets the deadline|will arrive on time|arrives early|(?:is|will be) (?:on time|early|late|overdue))\b', text, re.I):
        return 'unconfirmed_deadline_claim'
    if payload['delay_days'] is not None and payload['delay_days'] > 0 and re.search(r'\b(?:will arrive on time|meets the deadline|arrives early)\b', text, re.I):
        return 'contradictory_deadline'
    return None


def fallback(payload):
    method = METHODS[payload['objective']]
    evidence = payload.get('explanation_evidence') or {}
    scope = ('Only the required workshop was evaluated.' if evidence.get('required_sole_workshop')
             else 'The comparison applies to the evaluated feasible workshops under your constraints.')
    warnings = (' The estimated completion misses the registered due date.'
                if payload['delay_days'] is not None and payload['delay_days'] > 0 else '')
    due = f"due {payload['due_date']}" if payload['due_date'] else 'no confirmed due date; lateness cannot be assessed'
    if payload['objective'] == 'weighted_hybrid' and payload['due_date'] is None:
        method = 'the normalized score: 80% completion time and 20% defect exposure'
    differences = ''.join(f" {d['field']}: your message {d['supplied']}; registered value {d['recorded']}."
                          for d in payload.get('resolved_differences', []))
    return (
        'Verified summary (generated explanation unavailable or did not pass fact checks).\n\n'
        f"Allocation plan: {payload['order_id']} — {payload['allocated_pieces']} of {payload['pieces']} registered "
        f"{payload['product']} at {payload['workshop_name']} ({payload['workshop_id']}). "
        f"Estimated completion {payload['estimated_delivery_date']}; {due}; "
        f"cost {payload['estimated_cost']:.2f}; expected defect rate {payload['expected_defect_rate']:.2%}.\n\n"
        f"Allocation method: {payload['objective']} optimizes {method}.\n\n"
        f"Why this recommendation: The saved plan was selected using that objective. {scope}\n\n"
        f"Review before allocation: Estimates are not guarantees.{warnings}{differences} "
        'Check the registered details and explicitly confirm the recommendation card to allocate. No allocation has been committed.'
    )
