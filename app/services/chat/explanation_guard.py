"""Conservative claim checks and a factual fallback; no allocation calculations.

These checks catch unsupported identifiers/numbers and explicit contradictions.
They are not a general proof of natural-language correctness.
"""
import json
import re

METHODS = {
    'min_delay': 'earliest completion among the evaluated feasible plans',
    'min_cost': 'lowest production cost among the evaluated feasible plans',
    'min_defects': 'lowest expected defect rate among the evaluated feasible plans',
    'hybrid': 'the recorded time and quality score',
    'weighted_hybrid': 'the normalized score: 80% signed lateness and 20% defect exposure',
}
NUMBER = re.compile(r'(?<![\w-])-?\d+(?:,\d{3})*(?:\.\d+)?(?:%)?(?![\w-])')
IDENTIFIER = re.compile(r'\b(?:ORD-\d+|W\d+)\b', re.I)


def claim_problem(text, payload):
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
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
    if any(value not in evidence for value in dates):
        return 'unsupported_date'
    prose = IDENTIFIER.sub('', re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text))
    if any(float(v.replace(',', '').rstrip('%')) not in numbers for v in NUMBER.findall(prose)):
        return 'unsupported_number'
    if re.search(r'\b(?:we guarantee|guaranteed (?:delivery|quality|completion))\b', text, re.I):
        return 'unverified_guarantee'
    if payload['delay_days'] > 0 and re.search(r'\b(?:will arrive on time|meets the deadline|arrives early)\b', text, re.I):
        return 'contradictory_deadline'
    return None


def fallback(payload):
    method = METHODS[payload['objective']]
    evidence = payload.get('explanation_evidence') or {}
    scope = ('Only the required workshop was evaluated.' if evidence.get('required_sole_workshop')
             else 'The comparison applies to the evaluated feasible workshops under your constraints.')
    warnings = (' The estimated completion misses the registered due date.' if payload['delay_days'] > 0 else '')
    differences = ''.join(f" {d['field']}: your message {d['supplied']}; registered value {d['recorded']}."
                          for d in payload.get('resolved_differences', []))
    return (
        'Verified summary (generated explanation unavailable or did not pass fact checks).\n\n'
        f"Allocation plan: {payload['order_id']} — {payload['allocated_pieces']} of {payload['pieces']} registered "
        f"{payload['product']} at {payload['workshop_name']} ({payload['workshop_id']}). "
        f"Estimated completion {payload['estimated_delivery_date']}; due {payload['due_date']}; "
        f"cost {payload['estimated_cost']:.2f}; expected defect rate {payload['expected_defect_rate']:.2%}.\n\n"
        f"Allocation method: {payload['objective']} optimizes {method}.\n\n"
        f"Why this recommendation: The saved plan was selected using that objective. {scope}\n\n"
        f"Review before allocation: Estimates are not guarantees.{warnings}{differences} "
        'Check the registered details and explicitly confirm the recommendation card to allocate. No allocation has been committed.'
    )
