"""Validate current-message extraction before any allocation preparation or business writes."""
import re

from pydantic import ValidationError

from app.schemas.allocation import AllocationFields
from app.schemas.chat import AllocationExtraction
from app.services.chat.interpretation import (InterpretationValidationError, validate_interpretation,
                                              apply_due_date_context, pending_fields, rule_interpret, is_hypothetical)
from app.services.intake.evidence import normalize_patch
from app.services.intake.normalization import order_ids, workshop_mentions


class ExtractionValidationError(ValueError):
    def __init__(self, stage, detail):
        super().__init__(detail['reason'])
        self.stage, self.detail = stage, detail


def format_details(error, candidate, message, sequence, *, index=None, field=None):
    errors = [{'location': list(item['loc']), 'type': item['type']}
              for item in error.errors(include_input=False, include_context=False,
                                       include_url=False)] if isinstance(error, ValidationError) else []
    reason = 'INVALID_EXTRACTION_FORMAT'
    if errors and index is None:
        location = errors[0]['location']
        if len(location) >= 2 and location[0] == 'patch_operations' and type(location[1]) is int:
            index = location[1]
        if location and location[-1] == 'field' and errors[0]['type'] == 'literal_error':
            reason = 'UNKNOWN_FIELD'
        elif location and location[-1] in ('message_sequence', 'evidence') and errors[0]['type'] == 'extra_forbidden':
            reason = 'MODEL_SUPPLIED_EVIDENCE_METADATA'
    patches = candidate.get('patch_operations') if isinstance(candidate, dict) else None
    operation = (patches[index] if isinstance(patches, list) and index is not None and
                 0 <= index < len(patches) and isinstance(patches[index], dict) else {})
    evidence = operation.get('evidence')
    evidence = evidence if isinstance(evidence, dict) else {}
    return {'reason': reason, 'error_type': type(error).__name__, 'errors': errors,
            'field': field or operation.get('field'), 'operation_index': index,
            'operation': operation, 'source_message': message,
            'expected_message_sequence': sequence,
            'actual_message_sequence': operation.get('message_sequence', evidence.get('message_sequence')),
            'quote': operation.get('quote', evidence.get('quote'))}


def _validate_explicit_references(interpretation, message, conversation):
    """Reject omitted clear references so the existing repair loop can retry.

    This checks extraction completeness, not workshop eligibility or submission
    permission. Reuse the offline interpretation for supported hard assignments;
    never manufacture patches or override ambiguous, negated, or read-only input.
    """
    if is_hypothetical(message):
        return
    if re.search(r"\b(?:do not|don't|never|must not|should not)\s+(?:give|send|assign|allocate|use|dispatch)\b", message, re.I):
        return
    ids = order_ids(message, allow_short=True)
    if len(ids) != 1:
        return
    draft = conversation.get('draft', {})
    supplied = {p.field: p.value for p in interpretation.patch_operations if p.op == 'set'}

    baseline = rule_interpret(message, conversation)
    # A database-renamed alias must not be replaced by the offline seed vocabulary.
    mentioned = {wid for _, _, wid in workshop_mentions(message, conversation.get('workshop_names'))}
    required = {p.value for p in baseline.patch_operations
                if p.field == 'preferred_workshop' and p.op == 'set' and p.value in mentioned}
    expected = required.pop() if len(required) == 1 and len(mentioned) == 1 else None
    if not expected and interpretation.intent not in (
            'allocate_request', 'modify_constraints', 'answer_clarification', 'unsupported_or_ambiguous'):
        return
    expected_fields = {'order_id': ids[0]}
    if expected:
        expected_fields['preferred_workshop'] = expected
    missing = [field for field, value in expected_fields.items()
               if supplied.get(field, draft.get(field)) != value]
    if missing:
        field = missing[0]
        # Report every omitted reference together: there is only one repair attempt.
        raise ExtractionValidationError('evidence', {
            'reason': 'OMITTED_EXPLICIT_ORDER_ID' if field == 'order_id' else 'OMITTED_REQUIRED_WORKSHOP',
            'field': field, 'expected_value': expected_fields[field],
            'expected_fields': expected_fields, 'missing_fields': missing,
            'source_message': message, 'quote': message,
            'expected_message_sequence': conversation['current_sequence']})
    if not expected:
        return
    if (not baseline.ambiguity_reason and not baseline.unsupported_constraints and
            (interpretation.intent not in ('allocate_request', 'modify_constraints', 'answer_clarification') or
             interpretation.unsupported_constraints)):
        raise ExtractionValidationError('evidence', {
            'reason': 'MISCLASSIFIED_WORKSHOP_ASSIGNMENT', 'field': 'preferred_workshop',
            'expected_value': expected, 'source_message': message,
            'expected_message_sequence': conversation['current_sequence']})


def validate_candidate(candidate, *, message, conversation):
    sequence = conversation['current_sequence']
    try:
        extracted = AllocationExtraction.model_validate(candidate)
    except ValidationError as error:
        raise ExtractionValidationError('format', format_details(
            error, candidate, message, sequence)) from error
    extracted.patch_operations = [normalize_patch(p, message, conversation) for p in extracted.patch_operations]
    for index, patch in enumerate(extracted.patch_operations):
        if patch.field in AllocationFields.model_fields and patch.op == 'set':
            try:
                AllocationFields.model_validate({patch.field: patch.value})
            except ValidationError as error:
                raise ExtractionValidationError('format', format_details(
                    error, candidate, message, sequence, index=index, field=patch.field)) from error
    interpretation = extracted.with_evidence(sequence)
    try:
        validate_interpretation(interpretation, message, conversation)
    except InterpretationValidationError as error:
        raise ExtractionValidationError('evidence', error.detail) from error
    except (ValueError, KeyError, TypeError) as error:
        raise ExtractionValidationError('evidence', {'reason': str(error),
            'error_type': type(error).__name__, 'source_message': message,
            'expected_message_sequence': sequence}) from error
    _validate_explicit_references(interpretation, message, conversation)
    answered = {patch.field for patch in interpretation.patch_operations}
    if answered & pending_fields(conversation):
        interpretation.intent = 'modify_constraints'
    return apply_due_date_context(interpretation, message, conversation)


def salvage_due_date(candidate, error, *, message, conversation):
    """Keep grounded operations when only the due date fails evidence checks."""
    if not isinstance(candidate, dict) or not isinstance(error, ExtractionValidationError):
        return None
    patches = list(candidate.get('patch_operations') or [])
    current = error
    while (isinstance(current, ExtractionValidationError) and current.stage == 'evidence' and
           current.detail.get('field') == 'due_date'):
        index = current.detail.get('operation_index')
        if type(index) is not int or not 0 <= index < len(patches):
            return None
        del patches[index]
        if not patches:
            return None
        try:
            interpretation = validate_candidate({**candidate, 'patch_operations': list(patches)},
                                                message=message, conversation=conversation)
        except ExtractionValidationError as next_error:
            current = next_error
            continue
        if not interpretation.recommend_without_due_date:
            question = 'Please restate the due date including its year.'
            interpretation.ambiguity_reason = ', '.join(filter(None, [interpretation.ambiguity_reason, question]))
        return interpretation
    return None


def failure_message(stage, detail):
    field = detail.get('field')
    label = str(field)[:80] if field else 'fields'
    reason = detail['reason']
    if reason == 'OMITTED_EXPLICIT_ORDER_ID':
        return 'The order reference in your message was omitted during extraction. Please retry.'
    if reason == 'OMITTED_REQUIRED_WORKSHOP':
        return 'The required workshop in your message was omitted during extraction. Please retry.'
    if reason == 'MISCLASSIFIED_WORKSHOP_ASSIGNMENT':
        return 'The requested workshop assignment could not be interpreted reliably. Please retry.'
    if reason == 'UNKNOWN_FIELD':
        return f"Extracted field format validation failed: {label} is not a supported field."
    if stage == 'format':
        return ('Extracted field format validation failed.' if not field else
                f"Extracted field format validation failed for {label}.")
    if reason == 'EVIDENCE_QUOTE_MISMATCH':
        return f"The extracted {label} quote does not match the user message."
    if reason == 'EVIDENCE_SOURCE_NOT_FOUND':
        return f"The extracted {label} references an unavailable user message."
    if reason == 'STALE_EVIDENCE':
        return f"The extracted {label} references an earlier message without an explicit request to reuse it."
    return f"The extracted {label} could not be verified against the user message."


def recovery_hint(message, field):
    """Report recognized references without applying a partially valid request."""
    ids = order_ids(message, allow_short=True)
    reference = (' Order reference ' + ids[0] + ' is present in your message.') if len(ids) == 1 else ''
    help_text = {'due_date': ' Please restate the due date including its year.',
                 'order_date': ' Please restate the order date including its year.',
                 'preferred_workshop': ' Please name the required workshop or its ID.',
                 'exclusion': ' Please specify which workshops to exclude or allow again.',
                 'objective': ' Choose earliest completion, lowest cost, lowest defects, or a supported hybrid.'}
    return reference + help_text.get(field, ' Please restate the affected requirement.') + ' This message has not changed the allocation requirements.'
