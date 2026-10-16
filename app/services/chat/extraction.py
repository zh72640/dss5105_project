"""Validate current-message extraction before any allocation preparation or business writes."""
from pydantic import ValidationError

from app.schemas.allocation import AllocationFields
from app.schemas.chat import AllocationExtraction
from app.services.chat.interpretation import InterpretationValidationError, validate_interpretation


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


def validate_candidate(candidate, *, message, conversation):
    sequence = conversation['current_sequence']
    try:
        extracted = AllocationExtraction.model_validate(candidate)
    except ValidationError as error:
        raise ExtractionValidationError('format', format_details(
            error, candidate, message, sequence)) from error
    for index, patch in enumerate(extracted.patch_operations):
        if patch.field in AllocationFields.model_fields:
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
    return interpretation


def failure_message(stage, detail):
    field = detail.get('field')
    label = str(field)[:80] if field else 'fields'
    reason = detail['reason']
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
