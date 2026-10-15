"""Compatibility builder for parser_v1; business instructions live in the YAML catalog."""
from app.prompts import PromptCatalogError, get_registry
from app.schemas.parser_schema import SCHEMA_VERSION, json_schema
from app.services.intake.normalization import WORKSHOPS

PARSER_PROMPT_ID = "parsing.request"
PROMPT_VERSION = get_registry().get(PARSER_PROMPT_ID).version
SYSTEM_PROMPT = get_registry().get(PARSER_PROMPT_ID).system


def parser_snapshot(profile="default"):
    snapshot = get_registry().snapshot(PARSER_PROMPT_ID, profile=profile)
    if snapshot.definition.output_contract != SCHEMA_VERSION:
        raise PromptCatalogError("The parsing prompt must reference the supported parser schema.")
    return snapshot


def messages(message, reference_date, feedback=None, *, profile="default", snapshot=None):
    snapshot = snapshot or parser_snapshot(profile)
    available = {"reference_date": reference_date, "workshop_vocabulary": WORKSHOPS,
                 "output_schema": json_schema()}
    if set(snapshot.variables) - available.keys():
        raise PromptCatalogError("The parsing prompt declares an unsupported runtime variable.")
    bundle = snapshot.render(variables={name: available[name] for name in snapshot.variables},
                             user_message=message, retry_feedback=feedback)
    return bundle.as_messages()
