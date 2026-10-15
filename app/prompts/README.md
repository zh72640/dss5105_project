# Prompt catalog and message rendering

This package is the source of runtime LLM instructions. Offline conversation replies live in `app/offline/`; desk allocation summaries in `app/services/responses/`; UI labels remain in `app/ui/`. Providers read prepared messages and handle transport options and output-schema adaptation.

## Current catalog

| ID | Kind | Purpose |
| --- | --- | --- |
| `parsing.request` | prompt | The original `parser_v1` system instruction, runtime context, and four examples. |
| `parsing.fragment_policy` | fragment | The existing DeepSeek JSON-schema hint and follow-up/unsupported-constraint rules. |
| `parsing.retry` | fragment | The original retry instruction with validation or transient-provider feedback. |
| `conversation.intent`, `conversation.interpret`, `conversation.reply` | fragment / prompt | Chat v2 turn interpretation and grounded replies. |
| `agent.intent`, `allocation.extract`, `agent.reply` | prompt | Main Graph routing, allocation preparation, and Tool-loop instructions. |

The parsing definitions use version `parser_v1`; the conversation definitions use `chat_v2`; the Agent and allocation definitions use `v1`. The parser request declares `default`, `llm`, and `deepseek` profiles. Only the DeepSeek profile appends the fragment policy; this preserves the previous provider behavior. The retry remains one additional system message before the final user message. Gemini still sends its output schema through SDK configuration; the DeepSeek profile receives the unchanged parser schema as a runtime variable.

## Directory ownership

```text
app/prompts/
  models.py       immutable definitions, references and messages
  registry.py     safe YAML loading, catalog discovery and version selection
  renderer.py     variable rendering, composition and bundle metadata
  parser_v1.py    parser-specific prompt adapter
  catalog/
    manifest.yaml
    parsing/
      request_v1.yaml
      fragment_policy_v1.yaml
      retry_v1.yaml
    conversation/
    agent/
    allocation/
```

The catalog scans `.yaml` and `.yml` definitions recursively. Group files by business function, such as `parsing/`, `intent/`, `planning/`, or `reporting/`. Create a function directory when its first prompt is implemented. Do not store runtime customer data, passwords or API keys in these files.

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
  parsing.request: parser_v1
  parsing.fragment_policy: parser_v1
  parsing.retry: parser_v1
  intent.classify: intent_v1
```

Call the common API from the relevant business or workflow node:

```python
from app.prompts import get_registry

schema = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}
bundle = get_registry().render(
    "intent.classify",
    variables={"categories": ["allocation", "history"], "output_schema": schema},
    user_message=message,
)
messages = bundle.as_messages()
metadata = bundle.metadata
# Either existing LLMBackend or DeepSeekBackend accepts the same prepared bundle.
raw = backend.generate(bundle, output_schema=schema)
# Validate raw against the function's schema before using it.
```

Both model clients expose `generate(bundle, output_schema=..., json_output=...)` for any function, while `complete(message, reference_date, feedback)` retains the parser compatibility interface. Gemini adapts and sends the supplied schema through SDK configuration; DeepSeek requests JSON output and relies on the prepared schema hint plus caller validation. Omitting both options allows text output.

Adding a definition requires no registry conditionals or provider changes. Implement the function's workflow behavior and output validation separately. `output_contract` is a version label, not an executable schema; the caller supplies and validates its actual output schema. The existing parser adapter rejects a catalog contract different from its supported parser schema.

## Variables and examples

Use `${variable_name}` placeholders and declare every placeholder in `variables`. `$$` represents a literal dollar sign. Rendering performs one substitution pass; variable values and the final user message are never treated as templates or code. Missing/unknown variables produce explicit errors without echoing values.

Strings are inserted unchanged, dates use ISO format, and JSON-compatible values use JSON encoding. Few-shot examples are literal: `assistant` may be a string or a JSON value. Quote YAML values that must be strings, especially dates and words such as `yes`. Definitions contain only data; Python object tags and duplicate YAML mapping keys are rejected. File sizes are limited to 256 KB.

## Reusable fragments and profiles

A fragment declares its ID, version, description, variables and system text. It may contain context, but cannot contain examples, profiles, an output contract or another retry. A prompt can compose fragments through explicit profiles:

```yaml
profiles:
  default: []
  deepseek:
    - id: parsing.fragment_policy
      version: parser_v1
retry:
  id: parsing.retry
  version: parser_v1
```

References pin component versions so publishing a fragment's new default does not silently change existing prompt bundles. Provide `default` whenever profiles are defined. A retry fragment must declare `${feedback}`; profile fragments cannot use this reserved variable. Fragment system/context text is appended exactly as written, including its whitespace.

## Versions, snapshots and reproducibility

Publish a new YAML file and switch the manifest entry; keep previous version files for comparison and rollback. Restart the service to load a changed default catalog. The default registry is validated once and cached rather than reading files for every request. A fresh `PromptRegistry(path)` can validate or preview a candidate catalog independently.

Use `registry.snapshot(id, version=..., profile=...)` when multiple calls must share one definition set. Snapshots are immutable and pin all composition and retry definitions. Existing Gemini/DeepSeek backend instances bind a snapshot at construction, so their bounded retries share the same bundle. Rendered message dictionaries are fresh copies.

Every model parse records the original `prompt_version` field plus `prompt_bundle`: root ID/version, profile, output contract, component hashes, and a composite content hash. Metadata excludes runtime variable values and credentials. Generic feature callers record `bundle.metadata`; the existing parser records its bound parser snapshot automatically. The hash describes the definition set rather than a user's message. Session-level version pinning is a separate concern for future conversation features; current snapshots cover one backend operation and its retries.

`registry.list()` lists all versions and their metadata. Use `kind="prompt"` to select complete prompts or `active_only=True` for active versions; `registry.get(id, version)` returns an immutable definition. These APIs are the foundation for a future Prompt Lab. Editor UI, draft persistence and GitHub publication can call the catalog APIs without placing instructions in model clients.

## Compatibility and verification

`app/prompts/parser_v1.py` provides parsing prompt adapters for model clients. New workflow code imports `app.prompts` directly. Deterministic desk summaries live in `app.services.responses`.

Frozen fixtures in `tests/fixtures/prompt_messages_v1.json` and `response_messages_v1.json` were captured before migration. They verify exact provider message and reply parity. Registry tests cover generic function discovery, version selection, pinned retries, invalid YAML, unknown variables, metadata and the active parser/reply contracts. Provider tests use mock transports and make no real model calls.

```bash
uv run --locked python -m unittest tests.test_prompt_registry tests.test_gemini_sdk tests.test_deepseek -v
```
