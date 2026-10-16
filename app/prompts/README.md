# Prompt catalog and message rendering

This package is the source of runtime LLM instructions. Offline conversation replies live in `app/offline/`; desk allocation summaries in `app/services/responses/`; UI labels remain in `app/ui/`. Providers read prepared messages and handle transport options and output-schema adaptation.

## Current catalog

| ID | Kind | Purpose |
| --- | --- | --- |
| `conversation.intent`, `conversation.interpret`, `conversation.reply` | fragment / prompt | Chat v2 turn interpretation and grounded replies. |
| `agent.intent`, `allocation.extract`, `agent.reply` | prompt | Main Graph routing, allocation preparation, and Tool-loop instructions. |

The conversation definitions use `chat_v2`; the Agent and allocation definitions use `v1`.

## Directory ownership

```text
app/prompts/
  models.py       immutable definitions, references and messages
  registry.py     safe YAML loading, catalog discovery and version selection
  renderer.py     variable rendering, composition and bundle metadata
  catalog/
    manifest.yaml
    conversation/
    agent/
    allocation/
```

The catalog scans `.yaml` and `.yml` definitions recursively. Group files by business function, such as `conversation/`, `agent/`, or `allocation/`. Create a function directory when its first prompt is implemented. Do not store runtime customer data, passwords or API keys in these files.

## Add a prompt for a new function

Create a YAML definition. Stable IDs describe the function and operation; versions identify a published revision. For example:

```yaml
id: intent.classify
version: intent_v1
kind: prompt
description: Classify a user request.
variables:
  - categories
  - output_schema
system: |
  Choose an intent from ${categories}.
  Return JSON matching ${output_schema}.
output_contract: intent_v1
examples:
  - user: Allocate this order.
    assistant:
      intent: allocation
```

Add the default version to `catalog/manifest.yaml`:

```yaml
format_version: 1
active:
  intent.classify: intent_v1
```

Call the common API from the relevant business or workflow node. In this example, `model_registry` is the application's configured `ModelRegistry`:

```python
from app.prompts import get_registry

schema = {"title": "IntentClassify", "type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}
bundle = get_registry().render(
    "intent.classify",
    variables={"categories": ["allocation", "history"], "output_schema": schema},
    user_message=message,
)
messages = bundle.as_messages()
metadata = bundle.metadata
model = model_registry.get_model("llm", model_key)
raw = model.invoke(messages)
# Validate raw.text against the function's schema before using it.
```

For a configured non-`prompt` method, bind the current task schema with `model.with_structured_output(schema, method=method, include_raw=True)` and use its `parsed` and `raw` results. Bind tools at the current Agent call site with `model.bind_tools(allowed_tools)`. The registry caches only the base model.

Adding a definition requires no registry conditionals or provider changes. Implement the function's workflow behavior and output validation separately. `output_contract` is a version label, not an executable schema; the caller supplies and validates its actual output schema.

## Variables and examples

Use `${variable_name}` placeholders and declare every placeholder in `variables`. `$$` represents a literal dollar sign. Rendering performs one substitution pass; variable values and the final user message are never treated as templates or code. Missing/unknown variables produce explicit errors without echoing values.

Strings are inserted unchanged, dates use ISO format, and JSON-compatible values use JSON encoding. Few-shot examples are literal: `assistant` may be a string or a JSON value. Quote YAML values that must be strings, especially dates and words such as `yes`. Definitions contain only data; Python object tags and duplicate YAML mapping keys are rejected. File sizes are limited to 256 KB.

## Reusable fragments and profiles

A fragment declares its ID, version, description, variables and system text. It may contain context, but cannot contain examples, profiles, an output contract or another retry. A prompt can compose fragments through explicit profiles:

```yaml
profiles:
  default: []
  extended:
    - id: conversation.intent
      version: chat_v2
```

References pin component versions so publishing a fragment's new default does not silently change existing prompt bundles. Provide `default` whenever profiles are defined. A retry fragment must declare `${feedback}`; profile fragments cannot use this reserved variable. Fragment system/context text is appended exactly as written, including its whitespace.

## Versions, snapshots and reproducibility

Publish a new YAML file and switch the manifest entry; keep previous version files for comparison and rollback. Restart the service to load a changed default catalog. The default registry is validated once and cached rather than reading files for every request. A fresh `PromptRegistry(path)` can validate or preview a candidate catalog independently.

Use `registry.snapshot(id, version=..., profile=...)` when multiple calls must share one definition set. Snapshots are immutable and pin all composition and retry definitions. Rendered message dictionaries are fresh copies.

Agent model-call events record `bundle.metadata`: root ID/version, profile, output contract, component hashes, and a composite content hash. Metadata excludes runtime variable values and credentials. The hash describes the definition set rather than a user's message. Session-level version pinning is a separate concern for future conversation features; current snapshots cover one operation and its retries.

`registry.list()` lists all versions and their metadata. Use `kind="prompt"` to select complete prompts or `active_only=True` for active versions; `registry.get(id, version)` returns an immutable definition. These APIs are the foundation for a future Prompt Lab. Editor UI, draft persistence and GitHub publication can call the catalog APIs without placing instructions in model clients.

## Compatibility and verification

Workflow code imports `app.prompts` directly. Deterministic desk summaries live in `app.services.responses`.

Registry tests cover generic function discovery, version selection, invalid YAML, unknown variables, and metadata for active Chat and Agent prompts. Provider binding tests use dummy credentials and make no real model calls.

```bash
uv run --no-sync python -m unittest tests.test_prompt_registry tests.test_dynamic_agent -v
```
