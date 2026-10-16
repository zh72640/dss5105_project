"""LangChain chat-model initialization from ModelSpec."""
from app.schemas.parser_schema import json_schema

INTEGRATIONS = {"openai": "openai", "claude": "anthropic", "gemini": "google_genai", "deepseek": "deepseek"}


def build_model(spec):
    from langchain.chat_models import init_chat_model
    options = spec.options
    if spec.provider == "claude":
        options.setdefault("max_tokens", 4096)
    elif spec.provider == "gemini":
        options.setdefault("max_output_tokens", 4096)
    else:
        options.setdefault("max_tokens", 4096)
    model = init_chat_model(model=spec.api_model_id, model_provider=INTEGRATIONS[spec.provider],
                            api_key=spec.credential, timeout=spec.timeout, max_retries=0, **options)
    if spec.output_method != "prompt":
        schema = {"title": "DispatchParse", "description": "An allocation request.", **json_schema()}
        model = model.with_structured_output(schema, method=spec.output_method, include_raw=True)
    return model
