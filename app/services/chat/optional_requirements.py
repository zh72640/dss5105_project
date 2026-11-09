"""Evidence-bound handling of optional split requests that are not applied to a plan."""
import re

from app.services.intake.normalization import NUMBER, number

OPTIONAL_SPLIT = re.compile(
    rf"\bsplit\b[^.!?;\n]*?\bacross\s+(?P<count>{NUMBER})\s+(?:shops?|workshops?)\b"
    r"[^.!?;\n]*?\bif\b[^.!?;\n]*?\b(?:faster|sooner|quicker)\b[^.!?;\n]*[.]?", re.I)
LEGACY_REASON = re.compile(
    r'The request to split the order across (?:two|2) shops is an unsupported exact-split requirement[.]?', re.I)


def optional_split_quote(message):
    """Return an evidenced optional clause/count, excluding mandatory or negated splits."""
    match = OPTIONAL_SPLIT.search(message)
    if not match:
        return None
    prefix = re.split(r'[.!?;\n]', message[:match.start()])[-1]
    if (re.search(r"\b(?:do not|must not|should not|never|must|exactly)\s*$|don't\s*$", prefix, re.I) or
            re.search(r"\b(?:not|never|exactly|must|at least)\b|don't|%", match.group(), re.I)):
        return None
    count = number(match['count'])
    return (match.group(), match['count'].lower()) if type(count) is int and 2 <= count <= 8 else None


def normalize_optional_split(value, message, context):
    """Turn only a grounded optional split into a notice; keep other blockers intact.

    The existing model contract used one generic unsupported code for all cases.
    Its exact reported split-only refusal can recover when the offline evidence
    baseline finds no other unsupported requirement. Hard splits, budgets, and
    unrelated ambiguities are never relaxed here.
    """
    from app.services.chat.interpretation import rule_interpret
    from app.services.chat.extraction import ExtractionValidationError

    clause = optional_split_quote(message)
    codes = list(value.unsupported_constraints)
    baseline_blockers = rule_interpret(message, context).unsupported_constraints if clause else []
    legacy = (codes == ['unsupported_constraint'] and clause and
              LEGACY_REASON.fullmatch(value.ambiguity_reason or '') and
              not baseline_blockers)
    if legacy:
        codes = ['optional_split']
    if 'optional_split' not in codes:
        return value
    if not clause:
        raise ExtractionValidationError('evidence', {'reason': 'UNGROUNDED_OPTIONAL_SPLIT',
            'field': 'num_workshop_allowed', 'source_message': message})
    if any(code not in codes for code in baseline_blockers):
        raise ExtractionValidationError('evidence', {'reason': 'OMITTED_HARD_UNSUPPORTED_REQUIREMENT',
            'field': 'unsupported', 'source_message': message})
    quote, count = clause
    if any(p.field == 'num_workshop_allowed' and p.op == 'set' and (p.evidence.quote in quote or quote in p.evidence.quote)
           for p in value.patch_operations):
        raise ExtractionValidationError('evidence', {'reason': 'OPTIONAL_SPLIT_MUST_NOT_SET_WORKSHOP_LIMIT',
            'field': 'num_workshop_allowed', 'source_message': message})
    reason = value.ambiguity_reason
    if LEGACY_REASON.fullmatch(reason or ''):
        reason = None
    notice = {'code': 'OPTIONAL_SPLIT_NOT_APPLIED', 'field': 'num_workshop_allowed',
              'severity': 'warning', 'quote': quote, 'message_sequence': context['current_sequence'],
              'question': f'The request to split the order across {count} shops is an unsupported exact-split requirement.',
              'detail': 'This recommendation does not apply that split request; it uses the supported allocation constraints.'}
    return value.model_copy(update={'unsupported_constraints': [c for c in codes if c != 'optional_split'],
                                     'ambiguity_reason': reason, 'allocation_notices': [notice]})


def recover_legacy_split_issues(task, interpretation):
    """Drop only the isolated old two-issue refusal after new optional authorization.

    Any additional saved issue prevents recovery, preserving unrelated requirements.
    The caller owns a task copy and still performs all ordinary business checks.
    """
    if not interpretation.allocation_notices or interpretation.unsupported_constraints or interpretation.ambiguity_reason:
        return
    problems = task['issues']
    refusal = [p for p in problems if p.get('code') == 'AMBIGUOUS_MESSAGE' and
               p.get('field') == 'message' and LEGACY_REASON.fullmatch(p.get('question', ''))]
    generic = [p for p in problems if p.get('code') == 'unsupported_constraint' and
               p.get('field') == 'unsupported' and p.get('question') ==
               'This requirement cannot be computed: budget cap, exact split, or quality threshold. Withdraw it or use an existing business workflow.']
    if len(problems) == 2 and len(refusal) == len(generic) == 1:
        task['issues'] = []
