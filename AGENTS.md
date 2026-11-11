# Project development conventions

These instructions apply to the entire repository and to all development agents.

- `docs/architecture.md` is the design authority for the target architecture.
- Current code and tests establish existing business behavior and compatibility requirements; they do not define the target architecture.
- This file provides core constraints. Follow the separate Tool and Skill standards for their implementation.
- When an implementation conflicts with the target architecture, identify the gap and plan its migration. Do not change architectural principles to accommodate old code.

## 1. Project purpose

SweaterCo supports subcontracting decisions in fast-response garment manufacturing. Natural-language interaction helps dispatchers select external workshops and preserves explainable recommendations and decision records.

The system extracts orders and constraints, asks for clarification, evaluates workshop eligibility and feasibility, estimates delivery, proposes alternatives, and obtains allocation confirmation. Decisions account for capabilities, capacity, queues, quality, cost, and delivery requirements. The LLM interprets requests, coordinates tasks, and explains results; deterministic code controls calculations, business rules, and state changes.

## 2. Project structure

These are target responsibilities. New features must follow these boundaries; changes to existing code must account for callers and compatibility. Moving a file must not duplicate its business implementation.

| Directory | Responsibility |
| --- | --- |
| `app/agent/` | LLM Agent, Main Graph, allocation subgraph, Tool loop, Skill loading, checkpoint startup and recovery. |
| `app/offline/` | Chat v2 Offline interpretation graph and deterministic replies, separate from the native Tool Agent. |
| `app/skills/` | Markdown task instructions: steps, tools, branches, clarification, and fallback. |
| `app/tools/` | Named Agent capabilities: validate inputs, call Services or Repositories, and return structured results. |
| `app/services/` | Deterministic operations, calculations, scoring, optimization, business rules, and execution policy; `responses/` contains desk audit wording. |
| `app/allocator/` | Independent deterministic allocation: `allocate()`, eligibility, scoring, and integer splits; no DB or Agent dependencies. |
| `app/db/` | SQL, CRUD, Repositories, connections, transactions, and migrations. |
| `app/prompts/` | Versioned model prompts and their loader. |
| `app/schemas/` | HTTP, Agent State, Tool, and business data contracts. |
| `app/api/` | FastAPI routes, HTTP request handling, and responses. |
| `app/llm/` | ModelRegistry, LangChain model factory, selection and error contracts; not ORM models. |
| `app/config/` | Startup settings: database path, business date, and model configuration. |
| `app/core/` | ASGI lifespan, local accounts, and cookie authentication. |

See `docs/current_architecture.md` for the implemented paths and remaining gaps. Other directories retain their command, UI, data, evaluation, and runtime responsibilities.

## 3. Architecture and responsibility boundaries

The project follows **Agent–Skill–Tool–Service** layering. Existing implementations that depart from `docs/architecture.md` are not precedents for new features.

### Component responsibilities

- **LLM Agent:** Understand requests, select Tools using Skills, analyze results, propose actions, and explain. Do not implement calculations, SQL, or state changes in the Agent.
- **LangGraph Runtime:** Control node execution, routing, Agent–Tool loops, State, guards, suspension, and recovery. The LLM proposes; Runtime executes.
- **Skill:** A dynamically loaded Markdown resource describing steps, Tools, branches, clarification, and fallback. It is not an executable Python workflow, does not grant permissions, and does not replace deterministic rules.
- **Tool:** Expose an independent, named capability; validate arguments and call conditions; delegate and return structured results. Do not duplicate Service calculations or write SQL.
- **Service / Policy:** Independently enforce eligibility, constraints, estimates, scoring, planning, and state changes. Never assume that the Agent or Tool already performed business validation.
- **DB Repository:** Own SQL, CRUD, connections, transactions, and persistence; do not decide allocation strategy.
- **Prompt:** Keep templates and their loading separate from orchestration. Do not embed large prompts or deterministic rules in Agent nodes.

### Execution and dependencies

- Keep the Main Graph generic: task identification, routing, and results. Business preparation, rules, and completion conditions belong to business nodes or subgraphs.
- Intent, Business Task, and Skill do not require one-to-one mappings. A task may load zero, one, or several Skills; a Skill does not require its own Agent or subgraph.
- Reuse the model invocation, Tool binding, and Agent–Tool executor. Each business defines preparation, Skills, allowed Tools, and its Completion Guard.
- Define Tools in `app/tools/` and register them centrally. Expose them dynamically by task and permission. Do not accumulate business Tool implementations in Agent nodes or an internal ToolSet.
- Autonomous LLM business calls use Tools. Deterministic LangGraph nodes may call Services directly. Tools may call Services or use Repositories for simple queries.
- Tool visibility and execution permission are separate. Skill declarations do not authorize execution; Runtime validates calls and Service / Policy enforces final rules.
- Model silence or a success statement does not complete a task. A Completion Guard must verify the required results.
- Return structured `TaskResult` objects to the Main Graph. Never modify business state based on model prose.
- SQLite business tables are authoritative for orders, queues, recommendations, allocations, and tasks. Checkpoints store execution context and do not replace business records.

### Business and compatibility constraints

- Keep recommendation, confirmation, and commit separate. Chat v2 recommendations are previews. Allocation requires an explicit `confirm` action with the recommendation ID and current versions, followed by identity, version, and fresh-fact checks.
- Important writes require Service / Policy validation, transactions, version checks, audit, and appropriate idempotency. Model text cannot replace a committed result.
- Natural-language allocation uses `/api/chat/*` and `/chat`. Offline and LLM are Chat modes. Parser v1 (`/api/requests`), legacy `/api/sessions`, and `session_revise` jobs are retired; do not restore them as public APIs.
- Reuse `app/services/production/lifecycle.py` for production state, quantity, version, audit, and idempotency rules. Agent Tools must not implement separate production transitions. Tests may use `dispatch.seed_allocation`; it is an offline preparation helper, not an HTTP product entry point.
- Desk New request and conversation-editing entry points route to `/chat`. Keep recommendation-card confirmation semantics; do not rebuild the retired session editor.
- Reuse existing implementations when refactoring. Do not duplicate rules across layers or change algorithms, API behavior, or database semantics merely to reorganize files. Identify architectural gaps and plan migration first.

## 4. Tool and Skill development

Follow `docs/tool_development.md` for Tools and `docs/skill_development.md` for Markdown Skills. Tools expose capabilities without duplicating deterministic Service logic. Skills provide execution guidance without replacing Runtime guards or Service / Policy. Validate related schemas, registration, permissions, and business tests whenever Tools or Skills change.

## 5. Data, security, and runtime

- Never commit `.env`, API keys, personal CSV files, live SQLite databases, backups, or credentials. `.env.example` contains explanations and empty values only. Read configuration at startup and use that snapshot for model calls.
- Use temporary or isolated databases for tests, demos, and evaluations. Never treat `runtime/dispatch.sqlite3` as disposable. Verify the target path and backup status before changing real data or applying migrations.
- Preserve session ownership, HTTP authentication, administrator boundaries, version conflicts, and request-ID replay rules. Accounts share one business workspace; do not assume tenant isolation.
- Bind to `127.0.0.1` by default. Real model calls are optional online validation and must be distinguished from mocked or offline checks.

## 6. Development and verification

Run commands from the repository root:

```bash
uv sync --locked
uv run --locked python -m app.cli.setup
uv run --locked python -m app.server --backend offline
```

Start with tests relevant to the change, then run broader regression when justified:

```bash
uv run --no-sync python -X utf8 -m unittest tests.test_dynamic_agent -q
uv run --no-sync python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_*.cjs
python3 evaluation/check_repository.py
```

For documentation changes, check paths, links, commands, and descriptions against the implementation. Agent, Tool, transaction, or state-machine changes must cover relevant success, rejection/conflict, retry/replay, and old-data recovery paths. Evaluation scripts may write to ignored output directories; historical results are not evidence of the current run.

Before a multi-module architectural change, read the relevant architecture and development standards, identify gaps, prepare a file-level migration plan, and implement and verify in stages. Reuse existing code and avoid unrelated refactoring.

**Language:** All repository documentation, UI text, Agent replies, clarification questions, errors, explanations, identifiers, comments, docstrings, prompts, and Skills use English. Preserve non-English input compatibility with Unicode-escaped literals where needed; do not add non-English prose or generated reports to Git. Keep generated evaluation output and local notes out of the repository.

## 7. Delivery

Explain which files changed, why behavior changed, what was verified, and which checks were unavailable because of the environment or external services. State whether model/simulator evidence used real services, mocks, offline rules, or fixed-seed data. Locate conflicts with pre-existing uncommitted work before editing and preserve other contributors' changes.
