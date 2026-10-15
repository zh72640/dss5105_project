# Application file migration map

This map tracks migration against [architecture.md](architecture.md) and [AGENTS.md](../AGENTS.md). Status below reflects the working tree after the 2026-10-16 migration pass. Runtime behavior is confirmed by tests, not by this document alone. Live call chains: [current_architecture.md](current_architecture.md).

## Proposed directory shape

```text
app/
  main.py                 FastAPI application factory
  server.py               Local Uvicorn command entry
  api/                    HTTP routes, dependencies, error handling
  agent/                  LangGraph orchestration, state, recovery, Skill loading
  skills/                 Markdown task instructions
  tools/                  Agent-callable contracts, registry, thin handlers
  services/               Deterministic business rules and operations
  db/                     SQL, repositories, transactions, migrations
  schemas/                HTTP, Agent, Tool, and business data contracts
  prompts/                Versioned prompt resources and loader
  config/                 Settings and environment snapshots
  core/                   Model clients, authentication, application lifespan
  domain/                 Pure shared policies, only while their boundary is clear
  cli/                    Command-line entry points
  ui/                     Browser assets
```

`app/core/models/` means **LLM model runtime**; `app/schemas/` means **data contracts**.

## 1. Canonical implementation paths

Unchanged from the design table: keep implementations under `api/`, `agent/` (main/allocation/executor/runtime/skills/dynamic), `skills/`, `tools/{registry,operations,production}`, `services/`, `db/`, `prompts/`, `schemas/`, `config/`, `core/`, `domain/lifecycle.py`, `cli/`, `ui/`.

## 2. Compatibility import paths — status

Internal callers, tests, demos, and evaluation scripts use canonical imports. The following **shim modules were removed** after a zero-caller audit (production `.py` only):

| Removed | Canonical path kept |
| --- | --- |
| `app/core/config.py`, `app/core/model_settings.py` | `app/config/settings.py`, `app/config/model_settings.py` |
| `app/agent/toolset.py` | `app/tools/{registry,operations}.py`, `app/schemas/tool.py` |
| `app/agent/models/{factory,registry,result,specs}.py` | `app/core/models/*` |
| `app/agent/providers/{llm_client,deepseek_client}.py` | `app/core/providers/*` |
| `app/agent/prompt_catalog/**` (Python + duplicate YAML) | `app/prompts/**` |
| `app/agent/intake/{normalization,rule_parser,prompts}.py` | `app/services/intake/*`, `app/prompts/parser_v1.py` |
| `app/agent/conversation/{context,patches}.py` | `app/services/{conversation_context,constraint_patches}.py` |
| `app/tools/{allocation,eligibility,models}.py` | `app/services/{scoring,eligibility}.py`, `app/schemas/business.py` |
| `app/tools/allocator/**` | `app/services/planner.py` |
| `app/tools/database/**` | `app/db/*_repository.py` |

Empty packages `app/agent/providers/` and `app/agent/models/` may remain as namespaces.

## 3. Retained product flows (after 2026-10-16 retirement)

| Current files | Used by |
| --- | --- |
| `app/agent/router/chat_graph.py` + `app/agent/conversation/*` | Chat v2 **offline** interpret path |
| `app/agent/checkpoints.py` | SqliteSaver bootstrap at lifespan (was under router/checkpointer) |
| `app/agent/responses/{formatter,templates}.py` | Deterministic reply / audit summary text |
| `app/services/dispatch.py` helpers + `seed_allocation` | Lifecycle decide/apply helpers; offline test/demo seeding (**not** HTTP) |
| `app/services/chat.py` | Chat v2 LLM + offline facade |
| `app/agent/dynamic.py` via `runtime.py` | LLM Main Graph / Tool loop + checkpoint resume |

**Retired (deleted from product surface):** `/api/requests` (Parser v1), `/api/sessions*`, `/api/jobs` (`session_revise`), `services/{sessions,jobs,multimodel_gateway}.py`, legacy router graph/state/request_graph, `agent/intake` Parser stack, `legacy_backend_bridge`, Desk/legacy session editors (`sessions.js`, `legacy.html`). Desk new-request flows redirect to `/chat`.

## Recommended migration order — progress

1. **Freeze the map — completed 2026-10-16.**
2. **Remove import ambiguity — completed.** Callers on canonical paths; unused §2 shims and duplicate prompt YAML removed.
3. **Separate business boundaries — partial.** Clarified module roles via docstrings. `auth_me` SQL moved to `app/db/account_repository.py`. **Deferred:** splitting `agent_operations.execute`; moving remaining SQL out of `dispatch` / `read_models` / `core/security`; splitting `chat.py` LLM vs offline files.
4. **Retire Parser v1 + legacy sessions — completed 2026-10-16.** Chat v2 is the conversational product; Offline Chat mode retained inside Chat.
5. **Verify each phase — temporary DB + mock only; mock ≠ live LLM.**

## Differences noted (docs vs prior assumptions)

- Historical docs (`CODE_CLEANUP_CN.md`, `UNUSED_CODE_AUDIT_CN.md`) still mention old shim paths as history; they are not current import guides.
- `app/agent/prompt_catalog/` no longer exists; use `app/prompts/`.
