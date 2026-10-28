# Dispatch system guide

Current release: MVP v0.6, SQLite schema version 9. The original single-message allocation pipeline and legacy session API remain available for compatibility. The current LLM chat uses runtime application Skills, native model tool calls, deterministic domain guards, and persisted LangGraph checkpoints. Start with the [project overview](PROJECT_OVERVIEW_CN.md), [dynamic architecture](AGENT_SKILL_ARCHITECTURE.md), and [deployment guide](DEPLOYMENT_CN.md).

## Setup and first run

Use the repository's Python environment and lockfile. Start a local server with a separate database for experiments:

```bash
uv sync --locked
uv run --locked python -m app.server --db runtime/dispatch.sqlite3
```

The server initializes a new SQLite database and applies migrations 001–009 to an older supported database. Back up a real database before upgrading. Migration preserves existing orders, queue reservations, accounts, and sessions. Do not reset a demonstration by deleting assignment rows alone; queue and order state must be updated together. `python -m demos.week6_demo` and `python -m demos.lifecycle_demo` use isolated demonstration databases.

Sign in at `http://127.0.0.1:8000`. Create an ordinary account using `python -m app.cli.auth USERNAME` with the intended database path. The reserved administrator is provisioned by migration; ordinary account commands cannot reset it. Authenticated HTTP operations obtain the actor from the account. An explicit local `--no-auth` demo mode uses a demo identity and does not represent a production login.

## Workbench and chat

The English workbench provides Overview, Recommendations, Allocation history, Workshop explorer, Production, and a link to the standalone Conversation assistant at `/chat`. Both recommendation entry points use the same backend card and explicit confirmation endpoint. A proposed plan or preview does not write production assignments. The confirmation button submits only the displayed recommendation ID and current session version; the server verifies fresh business facts before committing.

Create a new chat session for an order. In `llm` mode, the model sees names and descriptions of application Skills, loads an applicable `SKILL.md`, and receives only that Skill's registered tool definitions. It can query orders or workshops, compare the restored single-workshop scores, check requirements, compute a full plan, save a recommendation, explain an existing result, revise constraints, or ask the user. The graph records messages, loaded Skill text and hash, tool results, plans, and pending questions. Deterministic code checks every state change.

A missing order ID or unresolved conflict stops calculation. A plan-affecting change supersedes the earlier card. If the user says “confirm, but change the quantity to 500,” the message is a revision, and the old card cannot be committed. Only the explicit `confirm` API action with that card's ID can submit it. A production completion, cancellation, lapse, or reassignment is a separate audited lifecycle operation.

The offline rules mode is a separate compatibility demonstration. It does not perform native model tool calls and should not be used as evidence that the dynamic Agent works with a live provider. Session mode and model selection are fixed when the session is created.

For detailed UI actions see [UI guide](UI_GUIDE_CN.md). For exact HTTP inputs and status codes see [HTTP API](UI_API_CN.md). Conversational allocation is Chat v2 only; see [SESSIONS_CN.md](SESSIONS_CN.md).

## Business calculations and state

The database contains registered order and workshop facts. The planner checks active status, product category, exclusions, capacity, batch limits, preferred workshop, deadline policy, integer piece conservation, and current queue. Planning objectives are `min_delay`, `min_cost`, `min_defects`, and a documented weighted `hybrid` heuristic. The full planner verifies each proposed split before a recommendation can be saved.

The restored `app/tools/allocation.py` supplies four earlier single-workshop functions for estimated completion time, lateness, defect rate, and a deadline-gated hybrid score. The Agent's `score_workshop` tool calls all four against real workshop, order, queue, and business-date data. They do not replace the current full split planner. Its weighted hybrid formula differs from the original deadline-gated one; see the [architecture guide](AGENT_SKILL_ARCHITECTURE.md).

Order states are `READY`, `WORKING`, `UNASSIGNED`, `COMPLETED`, and `LAPSED`. Chat allocation task states are `COLLECTING`, `BLOCKED`, `READY`, `RECOMMENDED`, `CONFIRMED`, and `CANCELLED`. These are different domain objects. A recommendation's valid, superseded, or confirmed status is also separate from either state list. Database facts and service transactions determine all business transitions; model text or checkpoint flags cannot do so.

Estimated queue time decays in calendar days, baseline workload first and then assignment reservations in FIFO order. An explicit completion event is required to record actual production, even when a predicted queue reaches zero. `cancel` releases a current assignment and returns unfinished pieces to `READY`; `lapse` ends further production. See [database mapping](DATABASE_SCHEMA_CN.md) and [production lifecycle](LIFECYCLE_CN.md).

## Commands and integrations

```bash
uv run --locked python -m app.cli --message "Allocate ORD-045 cheapest; exclude W3." --request-id cli-demo-001
uv run --locked python -m app.cli.lifecycle inspect ORD-045
uv run --locked python -m app.server --port 8001
```

The direct CLI's `--request R09` reads a historical fixture message; `--request-id` is the operation idempotency key. Use a new ID for a changed request and the same ID for an uncertain retry. The CLI's actor label is local audit data; it does not authenticate a web account. HTTP endpoints require login by default. `GET /api/ai/status` reports backend/configured/model without returning secrets.

Model credentials are configured on the server using the existing environment and model registry. OpenAI, Claude, Gemini, and DeepSeek adapters bind native tool schemas where supported. A selected backend without tool support returns `TOOLS_UNSUPPORTED`; a JSON-looking plan in normal text is never executed as tool calls. Live provider reliability and quality require a separate run with credentials and network access.

## Recovery, audit, and verification

The LLM Agent uses `chat-agent:<session_id>` as its stable LangGraph checkpoint thread. A clarification ends the current turn and saves the question; the next user message resumes on the same session with its pinned Skill snapshot. A completed turn reloads Skill permissions on the next message. If a process exits mid-run, retry with the same request ID to continue from the durable checkpoint. Every side-effecting tool also has a stable idempotency key and rechecks SQLite facts, because a graph node may run again.

The authenticated `GET /api/chat/sessions/{id}/trace` endpoint shows Skill hashes, tool arguments and results, state before and after, refusals, wait, resume, and finish events. `requests`, `decision_log`, and `lifecycle_events` provide older allocation and production audit records. A recommendation and allocation confirmation share a transaction with their audit and feedback.

Run the regression suites:

```bash
uv run --no-sync python -X utf8 -m unittest discover -s tests -p "test_*.py" -q
node tests/test_chat_ui.cjs
node tests/test_ui_state.cjs
```

The current local run passed 345 Python tests and 17 frontend tests. Some Python tests intentionally inject database failures and print their caught exception traces. The dynamic Agent acceptance model emits native tool calls through a test double; it verifies execution, guards, restart safety, and formula reuse without claiming live provider quality.

The application supports one order per current chat session. Unsupported budget caps, exact splits, and quality thresholds must be clarified or withdrawn rather than approximated. Master-data edits, automatic completion/lapse, streaming chat, and tenant-level order isolation are outside the implemented contract.
