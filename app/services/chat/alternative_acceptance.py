"""Ground acceptance of saved conditional alternatives without committing production."""
from copy import deepcopy
import re

from app.db import preparation_repository
from app.schemas.chat import AlternativeAcceptance, TurnInterpretation, PatchOperation, Evidence
from app.services.allocation.preflight import digest, issue

REFERENCE_FIELDS = ('order_id', 'objective', 'exclusion', 'num_workshop_allowed',
                    'preferred_workshop', 'deadline_required', 'due_date')
_ACCEPT = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|sure|please)[,\s]+)*(?:I\s+)?"
    r"(?:use|accept|apply|take|follow|go with|proceed with)\s+"
    r"(?:(?:your|the|this|that|previous|last|first|second|third|fourth|fifth)\s+)*"
    r"(?:suggestion|alternative|option|(?:suggested|recommended)\s+workshop)(?:\s*(?:[1-5]|alt-[a-f0-9]+))?"
    r"(?:\s+please)?[.!]*$", re.I)


class AlternativeAcceptanceError(ValueError):
    """A recoverable reference failure; allocation requirements remain unchanged."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def is_offline_acceptance_request(message):
    """Limited Offline grammar; LLM routing and authorization do not use this rule."""
    return bool(_ACCEPT.fullmatch(message.strip()))


def offline_acceptance_interpretation(message, options=()):
    """Build the limited Offline interpretation; LLM selection uses saved IDs directly."""
    index = None
    ordinal = re.search(r'\b(first|second|third|fourth|fifth)\b', message, re.I)
    numbered = re.search(r'\b(?:option|alternative|suggestion)\s*([1-5])\b', message, re.I)
    if ordinal:
        index = ('first', 'second', 'third', 'fourth', 'fifth').index(ordinal[1].lower())
    elif numbered:
        index = int(numbered[1]) - 1
    if index is not None and index >= len(options):
        return TurnInterpretation(intent='unsupported_or_ambiguous',
            ambiguity_reason='That option number is unavailable. Choose a current option.')
    selected = options[index] if index is not None and index < len(options) else None
    return TurnInterpretation(intent='modify_constraints',
        accept_alternative=AlternativeAcceptance(quote=message,
            alternative_id=selected['alternative_id'] if selected else None))


def validate_acceptance_quote(reference, message):
    """Ground semantic authorization in the entire current message, never a substring.

    The LLM interprets acceptance, negation and questions. Deterministic validation
    checks evidence and saved references without imposing a natural-language grammar.
    """
    if not message.strip() or reference.quote.strip() != message.strip():
        raise ValueError('UNGROUNDED_ALTERNATIVE_ACCEPTANCE')


def reference_issue_id(problem):
    """Stable reference for a pending clarification without changing its storage."""
    return 'issue-' + digest(problem)[:24]


def requirements_key(task):
    """Bind a suggestion to the order/requirements, independently of chat-only retries."""
    return digest({field: task['draft'].get(field) for field in REFERENCE_FIELDS})


def _offers(task, report, sequence=None):
    key = requirements_key(task)
    result = []
    for option in report.get('alternatives') or []:
        item = deepcopy(option)
        item.update(task_id=task['task_id'], requirements_key=key,
                    source_sequence=sequence)
        item['alternative_id'] = 'alt-' + digest([task['task_id'], key, option])[:24]
        result.append(item)
    return result


def _current(task, offers):
    key = requirements_key(task)
    return [deepcopy(o) for o in offers if o.get('task_id') == task['task_id'] and
            o.get('requirements_key') == key]


def pending_options(connection, task):
    """Read pending offers, recovering pre-feature sessions from preparation audit records.

    An empty list normally marks a consumed/invalidated set. The bounded recovery
    below handles old acceptances that were blocked by a sticky dialogue error
    before they ever reached planning, after the original constraints were restored.
    """
    report = task.get('report', {})
    if 'pending_alternatives' in report:
        if report['pending_alternatives']:
            return _current(task, report['pending_alternatives'])
        return _recover_uncompleted_acceptance(connection, task)
    if report.get('alternatives'):
        return _offers(task, report)
    for previous in preparation_repository.recent(connection, task['session_id']):
        old_task = previous.get('task', {})
        if old_task.get('task_id') != task['task_id'] or requirements_key(old_task) != requirements_key(task):
            continue
        old_report = old_task.get('report', {})
        if 'pending_alternatives' in old_report:
            return _current(task, old_report['pending_alternatives'])
        if old_report.get('alternatives'):
            return _offers(task, old_report)
    return []


def _recover_uncompleted_acceptance(connection, task):
    """Expose a legacy failed reference for explicit semantic resolution, never replay it.

    Successful preparations and closed tasks remain consumed. Recovery still needs
    a new current acceptance resolving the named dialogue errors, then fresh checks.
    """
    accepted = task.get('report', {}).get('accepted_alternative')
    questions = [reference_issue_id(p) for p in task['issues']
                 if p['code'] == 'AMBIGUOUS_MESSAGE' and p.get('field') == 'message']
    if task['state'] != 'BLOCKED' or not accepted or not questions:
        return []
    records = preparation_repository.recent(connection, task['session_id'])
    matching = [r for r in records if r.get('task', {}).get('task_id') == task['task_id']]
    attempts = [r for r in matching
                if r['task'].get('report', {}).get('accepted_alternative') == accepted]
    if not attempts or any(r.get('ready') for r in attempts):
        return []
    for record in matching:
        previous = record['task']
        if requirements_key(previous) != requirements_key(task):
            continue
        old = previous.get('report', {})
        offers = old.get('pending_alternatives') or _offers(previous, old)
        for option in _current(task, offers):
            if option['alternative_id'] == accepted['alternative_id']:
                option['recovery_issue_ids'] = questions
                return [option]
    return []


def track_report(task, report, previous_report, sequence=None):
    """Return a report that preserves unresolved offers across clarification turns."""
    result = deepcopy(report)
    if report.get('alternatives'):
        pending = _offers(task, report, sequence)
    elif report.get('ready_for_planning') or task['state'] in ('CONFIRMED', 'CANCELLED'):
        pending = []
    else:
        pending = _current(task, previous_report.get('pending_alternatives', []))
    result['pending_alternatives'] = pending
    if previous_report.get('accepted_alternative'):
        result['accepted_alternative'] = deepcopy(previous_report['accepted_alternative'])
    return result


def validate_workshop_reference(reference, message, options, workshop_names):
    """Reject an option reference that would discard one explicit workshop identity.

    Intent and negation remain LLM responsibilities. A mismatching concrete
    reference requires repair or clarification, never selection of another shop.
    """
    from app.services.intake.normalization import workshop_mentions
    mentioned = {wid for _, _, wid in workshop_mentions(message, workshop_names)}
    selected = next((o for o in options if o['alternative_id'] == reference.alternative_id), None)
    if selected is None and not reference.alternative_id and len(options) == 1:
        selected = options[0]
    if len(mentioned) == 1 and selected is not None:
        offered = {p['workshop_id'] for p in selected['plan']['allocation']}
        if not mentioned <= offered:
            raise ValueError('ALTERNATIVE_WORKSHOP_MISMATCH')
        if selected.get('required_changes', {}).get('preferred_workshop') not in mentioned:
            raise ValueError('EXPLICIT_WORKSHOP_REQUIRES_SELECTION')


def _select(reference, message, options):
    validate_acceptance_quote(reference, message)
    if not options:
        raise AlternativeAcceptanceError('ALTERNATIVE_NOT_FOUND',
            'No current alternative applies to these requirements. Request new options or state the change explicitly.')
    if reference.alternative_id and not any(o['alternative_id'] == reference.alternative_id for o in options):
        raise AlternativeAcceptanceError('ALTERNATIVE_STALE', 'That alternative is no longer current. Choose a current option.')
    if reference.alternative_id:
        return next(o for o in options if o['alternative_id'] == reference.alternative_id)
    if len(options) != 1:
        raise AlternativeAcceptanceError('ALTERNATIVE_SELECTION_REQUIRED',
            'There are multiple alternatives. Specify the option number to use.')
    return options[0]


def prepare_acceptance(connection, task, interpretation, sequence, mode, message):
    """Resolve authorization against current owned task data and derive only offered changes.

    The caller runs fresh preflight/planning after these patches. No saved plan is
    reused, no production state is changed, and unrelated blockers are retained.
    """
    if interpretation.accept_alternative is None:
        return task, interpretation
    revised = deepcopy(task)
    try:
        selected = _select(interpretation.accept_alternative,
                           message, pending_options(connection, task))
        from app.db.workshop_repository import names
        validate_workshop_reference(interpretation.accept_alternative, message, [selected], names(connection))
        resolved = set(interpretation.accept_alternative.resolved_reference_issue_ids)
        eligible_questions = {reference_issue_id(p) for p in task['issues']
                              if p['code'] == 'AMBIGUOUS_MESSAGE' and p.get('field') == 'message'}
        if not resolved <= eligible_questions:
            raise AlternativeAcceptanceError('ALTERNATIVE_QUESTION_STALE',
                'A referenced clarification is no longer current. Please retry against the current options.')
        if not set(selected.get('recovery_issue_ids', [])) <= resolved:
            raise AlternativeAcceptanceError('ALTERNATIVE_REFERENCE_UNRESOLVED',
                'Clarify the earlier suggestion reference before applying this recovered option.')
        if (interpretation.patch_operations or interpretation.unsupported_constraints or
                interpretation.answered_question_ids or interpretation.ambiguity_reason):
            raise AlternativeAcceptanceError('ALTERNATIVE_MIXED_CHANGES',
                'Accept an alternative separately from other requirement changes.')
        if selected.get('supported_mode') == 'offline' and mode != 'offline':
            raise AlternativeAcceptanceError('ALTERNATIVE_MODE_UNSUPPORTED',
                'This alternative requires Offline split planning. Choose a single-workshop option or use Offline mode.')
        changes = selected.get('required_changes', {})
        valid = bool(changes) and all(
            (field == 'preferred_workshop' and (value is None or (
                selected.get('offer_type') == 'workshop_candidate' and
                len(selected['plan']['allocation']) == 1 and
                value == selected['plan']['allocation'][0]['workshop_id']))) or
            (field == 'deadline_required' and value is False) or
            (field == 'num_workshop_allowed' and type(value) is int and 1 <= value <= 8) or
            (field == 'objective' and value == 'min_delay') for field, value in changes.items())
        if not valid:
            raise AlternativeAcceptanceError('INVALID_ALTERNATIVE', 'The saved alternative is invalid. Request new options.')
    except (AlternativeAcceptanceError, ValueError) as error:
        code = error.code if isinstance(error, AlternativeAcceptanceError) else 'UNGROUNDED_ALTERNATIVE_ACCEPTANCE'
        revised['issues'] = [p for p in revised['issues'] if not (
            p['code'].startswith('ALTERNATIVE_') or p['code'] == 'UNGROUNDED_ALTERNATIVE_ACCEPTANCE')]
        text = str(error) if isinstance(error, AlternativeAcceptanceError) else 'The alternative acceptance could not be verified against your message. Please specify the option to use.'
        revised['issues'].append(issue(code, 'alternative', text))
        return revised, TurnInterpretation(intent='modify_constraints')
    resolved = set(interpretation.accept_alternative.resolved_reference_issue_ids)
    # Only named dialogue ambiguities can be resolved by semantic reference
    # interpretation. Business constraints and field-specific blockers stay intact.
    revised['issues'] = [p for p in revised['issues'] if not (
        p['code'].startswith('ALTERNATIVE_') or p['code'] == 'UNGROUNDED_ALTERNATIVE_ACCEPTANCE' or
        (p['code'] == 'AMBIGUOUS_MESSAGE' and p.get('field') == 'message' and
         reference_issue_id(p) in resolved))]
    reference = interpretation.accept_alternative.model_copy(update={'alternative_id':selected['alternative_id']})
    derived = interpretation.model_copy(deep=True)
    derived.intent, derived.ambiguity_reason = 'modify_constraints', None
    derived.accept_alternative = reference
    derived.patch_operations = [PatchOperation(op='unset' if value is None else 'set', field=field,
        value=value, evidence=Evidence(message_sequence=sequence, quote=reference.quote))
        for field, value in changes.items()]
    revised['report']['pending_alternatives'] = []
    revised['report']['accepted_alternative'] = {'alternative_id':selected['alternative_id'],
        'required_changes':deepcopy(changes), 'message_sequence':sequence, 'quote':reference.quote,
        'resolved_reference_issue_ids':sorted(resolved)}
    return revised, derived
