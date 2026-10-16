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
  llm/                    LLM ModelRegistry (LangChain); not ORM
  allocator/              Deterministic allocate(); scoring and eligibility
  core/                   Authentication and application lifespan
  cli/                    Command-line entry points
  ui/                     Browser assets
```

`app/llm/` means **LLM model runtime**; `app/schemas/` means **data contracts**; `app/core/` means **lifespan + auth**.

## 1. Canonical implementation paths

Keep implementations under `api/`, `agent/`, `offline/`, `skills/`, `tools/`, `services/`, `allocator/`, `db/`, `prompts/`, `schemas/`, `config/`, `llm/`, `core/` (lifespan/security only), `cli/`, `ui/`.

## 2. Compatibility import paths — status

Internal callers, tests, demos, and evaluation scripts use canonical imports. The following **shim modules were removed** after a zero-caller audit (production `.py` only):

| Removed | Canonical path kept |
| --- | --- |
| `app/core/config.py`, `app/core/model_settings.py` | `app/config/settings.py`, `app/config/model_settings.py` |
| `app/agent/toolset.py` | `app/tools/{registry,operations}.py`, `app/schemas/tool.py` |
| `app/agent/models/*`, `app/core/models/*` | `app/llm/*` |
| `app/agent/providers/*`, `app/core/providers/*` | **deleted** (LangChain via `app/llm/factory.py` only) |
| `app/agent/prompt_catalog/**` (Python + duplicate YAML) | `app/prompts/**` |
| `app/agent/intake/{normalization,rule_parser,prompts}.py` | `app/services/intake/*`, `app/prompts/parser_v1.py` |
| `app/agent/conversation/{context,patches}.py` | `app/services/{conversation_context,constraint_patches}.py` |
| `app/tools/{allocation,eligibility,models}.py` | `app/allocator/{scoring,eligibility}.py`, `app/schemas/business.py` |
| `app/tools/allocator/**` | `app/allocator/` (`allocate`, planner, scoring, eligibility) |
| `app/services/{planner,scoring,eligibility}.py` | `app/allocator/` (max_workshops-only split; default 1) |
| `app/tools/database/**` | `app/db/*_repository.py` |

## 3. Retained product flows (after agent layout tidy)

| Current files | Used by |
| --- | --- |
| `app/agent/{runtime,main_graph,allocation_graph,executor,dynamic,skills}.py` | LLM Chat Main Graph / Allocation / Tool loop |
| `app/core/lifespan.py` | Application resource lifecycle and SqliteSaver bootstrap |
| `app/offline/{graph,interpreter,reply}.py` | Chat v2 **offline** interpret path (moved out of `agent/`) |
| `app/services/responses/{formatter,templates}.py` | Desk / audit allocation summaries |
| `app/services/dispatch.py` helpers + `seed_allocation` | Lifecycle decide/apply helpers; offline test/demo seeding (**not** HTTP) |
| `app/services/chat.py` | Chat v2 LLM + offline facade |

**Retired / removed:** `app/services/{planner,scoring,eligibility}.py` (now `app/allocator/`); `app/domain/` (lifecycle rules folded into `app/services/lifecycle.py`); `app/core/providers` (direct backends); former `app/core/models` (now `app/llm`); empty agent `models/` & `providers/`; `router/` & `conversation/` (now `app/offline/`); `responses/` (now `app/services/responses/`); Parser v1 / old Session APIs (earlier).

## Recommended migration order — progress

1. **Freeze the map — completed 2026-10-16.**
2. **Remove import ambiguity — completed.**
3. **Separate business boundaries — partial.** Offline + responses moved out of `agent/`. **Deferred:** splitting `agent_operations.execute`; remaining SQL in `dispatch` / `read_models` / `core/security`; splitting `chat.py` LLM vs offline files.
4. **Retire Parser v1 + legacy sessions — completed 2026-10-16.**
5. **Tidy `app/agent/` layout — completed.** Offline under `app/offline/`; LLM runtime flat under `app/agent/`.
6. **Split `app/llm/` from core; delete direct providers — completed.** `core/` is lifespan + auth only.
7. **Fold `domain/lifecycle` into `services/lifecycle` — completed.** `app/domain/` removed.
8. **Verify — temporary DB + mock only; mock ≠ live LLM.**

## Differences noted (docs vs prior assumptions)

- Historical docs (`CODE_CLEANUP_CN.md`, `UNUSED_CODE_AUDIT_CN.md`) still mention old shim paths as history; they are not current import guides.
- `app/agent/prompt_catalog/` no longer exists; use `app/prompts/`.
