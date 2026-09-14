"""Single-message parser v1; validated data and retry telemetry are separate."""
import json
import os
import time
from dataclasses import dataclass
from datetime import date
from app.schemas.parser_schema import ParseResult, SCHEMA_VERSION
from .llm_client import (BackendError, LLMBackend, GEMINI_MODEL, GEMINI_PROVIDER,
                         GEMINI_TEMPERATURE, GEMINI_THINKING_LEVEL)
from .prompts import PROMPT_VERSION
from .rule_parser import extract
from .validator import ValidationError, validate_output


class RuleBackend:
    name = "offline"
    model = "rules_v1"
    temperature = None

    def complete(self, message, reference_date, feedback=None):
        return json.dumps(extract(message, reference_date))


@dataclass
class ParserOutcome:
    parsed: ParseResult | None
    telemetry: dict
    error: str | None = None


def parse_with_telemetry(message: str, context_messages=None, *, backend=None,
                         reference_date=date(2026, 4, 1)) -> ParserOutcome:
    start = time.perf_counter()
    owned_backend = None
    telemetry = {"prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
                 "backend": str(backend or os.getenv("PARSER_BACKEND", "offline")),
                 "model": None, "temperature": None, "retry_count": 0, "attempts": []}
    def finish(parsed, error=None):
        if owned_backend is not None:
            owned_backend.close()
        telemetry["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        telemetry["validation_result"] = "valid" if parsed else "parser_error"
        return ParserOutcome(parsed, telemetry, error)
    if context_messages:
        return finish(None, "context_not_supported")
    if not isinstance(message, str) or not message.strip() or len(message) > 10000:
        return finish(ParseResult(parse_status="invalid", ambiguities=["invalid_message"]))
    try:
        if backend is None:
            backend = os.getenv("PARSER_BACKEND", "offline")
        if isinstance(backend, str):
            if backend not in ("offline", "llm"):
                raise BackendError("unknown_parser_backend", False)
            if backend == "llm":
                telemetry.update(provider=GEMINI_PROVIDER, model=GEMINI_MODEL,
                                 temperature=GEMINI_TEMPERATURE, thinking_level=GEMINI_THINKING_LEVEL)
                backend = LLMBackend()
                owned_backend = backend
            else:
                backend = RuleBackend()
        telemetry.update(backend=backend.name, model=backend.model, temperature=backend.temperature)
        if getattr(backend, "provider", None):
            telemetry["provider"] = backend.provider
        if getattr(backend, "thinking_level", None):
            telemetry["thinking_level"] = backend.thinking_level
    except (BackendError, ValueError) as error:
        return finish(None, str(error))
    feedback = None
    for attempt in range(2):
        raw = None
        telemetry["retry_count"] = attempt
        try:
            raw = backend.complete(message, reference_date, feedback)
            parsed = validate_output(raw, message, reference_date)
            telemetry["attempts"].append({"raw_output": raw, "validated_output": parsed.to_dict(), "error": None})
            return finish(parsed)
        except (ValidationError, BackendError) as error:
            feedback = str(error)
            telemetry["attempts"].append({"raw_output": raw, "validated_output": None, "error": feedback})
            if isinstance(error, BackendError) and not error.retryable:
                break
    return finish(None, feedback)


def parse_request(message: str, context_messages=None, **kwargs) -> ParseResult:
    outcome = parse_with_telemetry(message, context_messages, **kwargs)
    if outcome.error:
        raise ValidationError("parser_error:" + outcome.error)
    return outcome.parsed


def fake_parse_request(text):
    """Explicit Week 4 fixture compatibility; never used by the live pipeline."""
    from .legacy_parser import parse_request as legacy
    return legacy(text)
