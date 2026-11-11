# SweaterCo Dispatch Desk

A local subcontracting dispatch system for garment manufacturing. Dispatchers describe orders and requirements in English, compare workshop recommendations, explicitly approve allocations, and track production with an audit trail.

The application uses FastAPI, LangGraph, SQLite, and a browser UI. LLM mode supports configured OpenAI, Claude, Gemini, and DeepSeek models; Offline mode provides a deterministic demonstration. Recommendations and order reviews require explicit human confirmation before business changes.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository root:

```bash
uv sync --locked
uv run --locked python -m app.cli.setup
uv run --locked python -m app.server --backend offline
```

Open <http://127.0.0.1:8000> and sign in with the account created during setup. Setup imports the bundled 120 orders and eight workshops or your own CSV files. It refuses to overwrite an existing database. Existing users should back up their database and skip setup.

For a configured model, keep credentials in a local `.env` based on `.env.example`, then start explicitly with that file:

```bash
uv run --locked --env-file .env python -m app.server --mode llm --model-key deepseek
```

Use your configured model alias. The application does not load `.env` automatically. Configuration is read at startup; existing conversations retain their mode and model. See [setup and model configuration](docs/setup.md) for data import, accounts, providers, and supported settings.

## Using the application

- **Requests:** Describe an allocation, answer clarification questions, compare plans, then use **Confirm allocation**. Recommendation text and candidate selection do not commit production.
- **Order entry:** Use **Orders → Add order**, or register an order in a Request. Missing orders require creation confirmation. Identical orders are not duplicated. Corrections require verification of every difference, the exact order ID, and a reason. Approvals and rejections appear in **Registration history**.
- **Operations:** Inspect workshop queues and order progress, then record production completion, cancellation, lapse, or reassignment through the controlled forms.
- **Audit:** Review saved decisions, comparisons, actors, reasons, and production events. Session access is owner-scoped; accounts share the local business workspace.

Example conversational registration:

> Add order ORD-901 for ABC: 300 knitted vests, TOPS, ordered 2026-11-11, due 2026-11-25.

Reply with missing information, then confirm or decline on the review card. After registration, send `Allocate ORD-901.` to request a separate allocation preview.

## Documentation

| Guide | Contents |
| --- | --- |
| [Setup](docs/setup.md) | Installation, CSV import, accounts, and model settings. |
| [Deployment](docs/deployment.md) | Local operation, backup, schema upgrades, and recovery. |
| [Order registration](docs/order_registration.md) | Manual and conversational entry, verification, and audit. |
| [Operations](docs/operations.md) | Dashboard metrics, queues, and order tracking. |
| [Testing](docs/testing.md) | Regression, isolated browser checks, simulations, and evaluation boundaries. |
| [Demo reset](docs/demo.md) | Explicit reset of a named demo database with backup. |
| [Current implementation](docs/current_architecture.md) | Runtime paths, calculations, state, and remaining gaps. |
| [Target architecture](docs/architecture.md) | Responsibilities, dependency rules, and workflow contracts. |
| [Database](docs/database.md) | Tables, transactions, versions, and authority. |
| [Known limits](KNOWN_ISSUES.md) | Product and validation boundaries. |

Contributors should read [AGENTS.md](AGENTS.md), [Tool standards](docs/tool_development.md), [Tool categories](docs/tool_categories.md), [Skill standards](docs/skill_development.md), and the [prompt catalog guide](app/prompts/README.md).

## Verification

```bash
uv run --locked python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_*.cjs
python3 evaluation/check_repository.py
```

Python tests use isolated databases and mocked model transports; Node tests cover client behavior. Live-provider and visual-browser checks are separate. The [testing guide](docs/testing.md) documents the full workflow. Keep generated reports, screenshots, credentials, and live databases out of Git; retained evaluation fixtures are inputs to reproducible checks.

The current database schema is version 11. Natural-language allocation uses `/api/chat/*`; `/api/requests`, legacy `/api/sessions`, and legacy jobs are retired. API contracts are available at `/docs` after signing in. The default server binds to `127.0.0.1` and supports one local process with a shared business workspace.
