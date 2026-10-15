# SweaterCo Dispatch Desk — MVP v0.6

**2026-10-15 Agent architecture:** LLM chat sessions use native model tool calls in a durable LangGraph loop. Runtime-loaded Skills guide tool selection; guarded tools and SQLite transactions control business state. Single-workshop scoring is implemented in `app/services/scoring.py`; `app/tools/allocation.py` remains an import compatibility path. See the [current architecture](docs/current_architecture.md) and [Agent, Skill, and state architecture](docs/AGENT_SKILL_ARCHITECTURE.md). Offline rules mode remains a separate demo.

**Multi-model support:** startup-only environment configuration, OpenAI / Claude / Gemini / DeepSeek model catalogues, and request-level LLM / Offline and model selection are available. See [setup and data import](docs/UV_SETUP.md) and the [Agent architecture](docs/AGENT_SKILL_ARCHITECTURE.md).

A local subcontracting dispatch system for DSS5105 Track 2: natural-language requests, clarification drafts, workshop eligibility and queue analysis, recommendations with explicit approval, production tracking, and audit history.

**2026-10-15 Chat:** `/chat` uses persistent owner-scoped sessions. AI mode runs the Skill-guided native tool Agent described above; Offline mode remains a rules demo. Recommendations appear in the existing Recommendations page, and either entry point can confirm a specific plan once. Successful confirmation saves factual feedback to the conversation. SQLite schema v9 adds durable Agent run and tool trace tables while preserving v1 APIs. Live provider quality is not established by offline or mocked tests.

**2026-10-13 account update:** regular users and a built-in administrator are supported. SQLite schema v7 preserves existing user accounts and provisions `admin`. Ordinary registration creates regular users; administrator credentials are supplied privately. An authenticated administrator sees an `admin` badge in the upper-left corner.

**2026-10-13 architecture update:** HTTP runs on FastAPI with `/docs`, `/redoc`, and `/openapi.json`; LangGraph orchestrates conversation turns; SQLite jobs support idempotent enqueueing, lease recovery, bounded retries, and cancellation checks before business writes. Modules are grouped by responsibility, and existing API paths and CLI commands remain available. See the [application architecture](docs/AGENT_ARCHITECTURE_CN.md).

**2026-10-08 update:** DeepSeek environment configuration, allocation summaries, recent approvals, targeted clarification questions, an editing form that works without AI, and Small / Medium / Large text settings. See the [setup guide](docs/UV_SETUP.md) and [known limits](KNOWN_ISSUES.md).

**2026-10-16 API retirement:** Parser v1 (`/api/requests`), legacy `/api/sessions`, and `session_revise` jobs were removed. Conversational allocation is Chat v2 (`/api/chat/*`, `/chat`); Desk new requests redirect there. Account, setup, and lifecycle CLIs remain (`app.cli.auth`, `app.cli.setup`, `app.cli.lifecycle`).

**2026-10-14 source cleanup:** obsolete CSV allocation code and many old import paths were removed. See the [file migration map](docs/app_file_migration_map.md).

## Quick start with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), download the repository, and run these commands from its root. No manual virtual-environment activation is needed.

```bash
# Install the locked dependencies and selected Python environment
uv sync --locked

# First run only: choose bundled or personal CSV files and create a regular account
uv run --locked python -m app.cli.setup

# Start without an external model (rules parser)
uv run --locked python -m app.server --backend offline

# Or Gemini parsing: copy .env.example to .env and set GEMINI_API_KEY
uv run --locked --env-file .env python -m app.server --backend llm
```

Open <http://127.0.0.1:8000> and sign in with the account created during setup. The app does **not** auto-load `.env`; use `uv run --env-file .env` locally, or inject the same variables in deployment. The bundled data contains 120 orders and 8 workshops. Personal CSV files use the same format as `data/orders.csv` and `data/workshops.csv`; the original files are not modified. **Already have a database? Back it up and skip setup.** Setup refuses to overwrite any existing database file. See the [uv, data import, and account guide](docs/UV_SETUP.md) for supported CSV fields, private data, dates, and troubleshooting.

To use personal files with a separate database:

```powershell
uv run --locked python -m app.cli.setup --orders "D:/private/orders.csv" --workshops "D:/private/workshops.csv" --db runtime/personal.sqlite3 --as-of 2026-10-09 --username professor
uv run --locked python -m app.server --db runtime/personal.sqlite3 --backend offline
```

## Accounts and administrator access

Setup creates your first **regular user**. Create additional regular users with `uv run --locked python -m app.cli.auth another_user`. Explicitly reset a regular user's password with `uv run --locked python -m app.cli.auth another_user --reset-password`. Use the same `--db` argument when managing a separate database. Duplicate registration never changes an existing password. Account registration currently takes place in the terminal.

Each new database and upgraded older database receives the built-in **`admin`** account. Use the maintainer-supplied password in the usual sign-in form. Administrator sessions show `admin` below the brand in the upper-left corner; the badge is hidden for regular users and after sign-out. The source contains only a salted password hash. The password is omitted from documentation and logs.

The name `admin`, including case variants, is reserved. Ordinary registration and account-reset commands cannot create, promote, or reset an administrator. Older accounts retain the `user` role and their existing passwords. If an older database already contains an account named `admin` or a case variant, migration stops with a conflict message and rolls back; back up the database and resolve that account name before upgrading. Repeated startup does not reset passwords or duplicate accounts.

Regular users and administrators share the current business workspace. Future administrator tools can use the backend role guard. The explicit `--no-auth` demonstration mode uses a regular `local-demo` identity. People who control their local source code and database can change their own installation's permissions. Separate local databases remain independent.

## Using the desk

Open the conversation assistant at `/chat` (Desk “New request” redirects there). Resolve clarifications, review the recommendation card, then confirm explicitly. Production supports partial/full completion, reversal, lapse, and reassignment from the desk. LLM turns enter `app/agent/runtime.py` → main graph / allocation subgraph / Tool loop in `app/agent/dynamic.py`. Business services live in `app/services/` and FastAPI routes in `app/api/`. After signing in, open the [API documentation](http://127.0.0.1:8000/docs) in the same browser.

## Prompt and reply organization

The Agent discovers `app/skills/*/SKILL.md` at runtime. The allocation subgraph loads its recommendation Skill after fixed preparation; compatible tasks can request Skills from the catalog. Loaded instructions and their hashes are saved for recovery. A completed turn clears loaded Tool permissions; a pending question keeps its Skill snapshot. Versioned YAML prompts for both current and compatibility paths live under `app/prompts/catalog/`.

Business replies in LLM chat are grounded in Tool results and saved facts. The server checks direct commitment and production-success claims against authoritative results. Compatibility responses live in `app/agent/responses/` and `app/agent/conversation/reply.py`; the canonical prompt catalog is described in its [guide](app/prompts/README.md).

## Documentation

- [Dynamic Agent, Skills, tools, and business state](docs/AGENT_SKILL_ARCHITECTURE.md): current execution, recovery, tool contracts, scoring semantics, and verification.
- [Dynamic Agent acceptance](docs/AGENT_ACCEPTANCE.md): scenario matrix, reproducible tool trace, and live-provider boundary.
- [Current architecture](docs/current_architecture.md): running paths, boundaries, and data flow.
- [File migration map](docs/app_file_migration_map.md): canonical paths, import compatibility, and older business flows.
- [Target architecture](docs/architecture.md): intended responsibilities and dependency rules.
- [Setup and data import](docs/UV_SETUP.md): environment, accounts, and first run.
- [Known limits](KNOWN_ISSUES.md): provider acceptance, data, optimization, and deployment boundaries.

## Demonstrations and verification

```bash
uv run --locked python -X utf8 -m demos.lifecycle_demo
uv run --locked python -X utf8 -m demos.week6_demo

# Tests use temporary databases and mocked model transports.
uv run --locked python -X utf8 -m unittest discover -s tests -v
# Full acceptance also rewrites reports under evaluation/results/.
uv run --locked python -X utf8 evaluation/verify_mvp.py
uv run --locked python -X utf8 evaluation/verify_ui.py

# Frontend controller tests require Node 18+; running the app does not require Node/npm.
node --test tests/test_ui_state.cjs
uv run --no-sync python -X utf8 -m evaluation.verify_dynamic_agent
```

The prompt organization update passed **266 Python tests and 9 frontend tests**. Frozen fixtures verify exact parity for 4 provider-message bundles and 35 user replies; registry checks cover adding a new function, version selection, pinned retries, variable validation, and compatibility imports at the time of that update. See the [prompt verification report](evaluation/results/prompt_catalog_verification.json). Model transports are mocked; these results do not establish live provider quality.

The account-role update passed **247 Python tests and 9 frontend tests**, with browser checks for administrator sign-in, the upper-left badge, refresh, sign-out, and regular-user sign-in. See the [account verification report](evaluation/results/account_roles_verification.json).

The framework refactor passed 232 Python tests and 7 frontend tests, 60/60 offline parsing cases, 30/30 original business behavior cases, 14 simulator configurations, and continuous HTTP demonstrations. These historical results are recorded in the [framework verification report](evaluation/results/framework_refactor_verification.json). The account update adds tests in `tests/test_account_roles.py` and extends the frontend controller checks. Historical v0.5 results remain in [verification_summary.json](evaluation/results/verification_summary.json); [ui_latency.json](evaluation/results/ui_latency.json) contains historical measurements and does not represent current endpoints or online model latency.

Historical Safari checks covered the homepage, large text, request creation, clarification, editing, approval, and summary display. See [known limits](KNOWN_ISSUES.md) for production, audit export, and mobile boundaries. Automated checks do not establish live Gemini or DeepSeek connectivity and quality.

## Current boundaries

The server defaults to the latest queue snapshot date in the selected database. Bundled setup suggests `2026-04-01`; personal imports allow another date. Legacy dispatch/session CLIs still require an explicit matching `--as-of` for personal data. Daily approval statistics use the actual UTC date. Application v0.6 uses DB v9, Chat v2 and Session/Parser/Prompt v1, and Pipeline v0.2. The server binds to `127.0.0.1` and runs as one process at low concurrency. Accounts have `user` and `admin` roles and share one business workspace without tenant isolation; chat v2 sessions are owner-scoped.

DeepSeek reads `DEEPSEEK_API_KEY` and defaults to `deepseek-flash`; start with `python -m app.server --backend deepseek`. Without an explicit backend or `PARSER_BACKEND`, a configured DeepSeek key selects DeepSeek; otherwise the parser uses offline rules. Existing conversations retain their original backend. Gemini uses `--backend llm`. No real model calls were made for the architecture, account, or prompt organization updates; the 2026-10-02 Gemini evaluation's HTTP 429 result remains historical. Global model throttling/backoff, workshop capacity editing, automatic expiry, and independent dataset evaluation remain future work.
