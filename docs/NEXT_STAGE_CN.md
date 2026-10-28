# Current handoff and next verification

Updated 2026-10-15 for MVP v0.6 and database schema v9. Read the [dynamic Agent architecture](AGENT_SKILL_ARCHITECTURE.md), [system guide](SYSTEM_GUIDE_CN.md), [deployment guide](DEPLOYMENT_CN.md), and [database mapping](DATABASE_SCHEMA_CN.md) before changing workflow or transactions. Historical v0.5 metrics in older acceptance records describe their original release and should not be presented as current live-model acceptance.

## Implemented paths

- The original direct allocation pipeline, legacy session_v1, lifecycle events, jobs, login, workbench, and chat v2 remain available.
- LLM chat uses native provider tool calls with runtime-discovered application Skills. Its Toolset includes order/workshop/queue reads, the four restored `app/tools/allocation.py` scores, grounded requirement edits, preflight, full-plan calculation, recommendation save and inspection, clarification, and production events.
- Deterministic services control task states, recommendation versioning, eligibility, capacity, integer quantity conservation, confirmation, queues, auditing, and lifecycle transactions. A preview or recommendation does not commit production allocation.
- LangGraph checkpoints and the Agent run/tool/event ledger persist work across retries. Side-effecting calls are idempotent, including a production event interrupted after the business transaction.
- The English UI exposes a standalone conversation page and a workbench recommendation panel with one shared confirmation operation. Session trace is owner-scoped at `GET /api/chat/sessions/{id}/trace`.

The latest local regression run passed 345 Python tests and 17 frontend tests. The dynamic Agent tests feed native `AIMessage.tool_calls` from a scripted model and verify the actual graph and tool execution path. This is evidence for runtime architecture, state guards, and replay behavior; it does not measure real provider response quality.

## Remaining external acceptance

Run an end-to-end conversation with a configured live model and save the visible Skill/tool trace. A previous attempt to contact the configured provider from this workspace failed at DNS lookup, before a model response. Do not substitute offline rules or mocked tool calls for this acceptance. Keep provider keys out of logs and committed files.

The external Data Schema2 ERD/DDL is still absent from this repository. A schema compatibility claim requires the source schema and a column-by-column comparison with migrations 001–009. If a change is needed, add a migration; do not rewrite a migration already used by a database.

Historical Gemini evaluation on 2026-10-02 reported a successful smoke test but 46 of 60 full-run cases ended in HTTP 429. That result establishes a rate-limit failure, not the accuracy of the missing model outputs. DeepSeek live quality was also not established by the older mocked tests. A new live evaluation should include failures in its denominator and record provider conditions.

## Product and data questions

- Confirm the intended primary allocation objective, hybrid weights, calendar-day policy, and cancel/lapse/reassignment interpretation with the business owner before changing the planner or queue model.
- Workshop closure, capacity edits, and queue corrections need a versioned, audited operation that preserves `baseline + active reservations = current queue`; direct column editing can break conservation.
- Exact split, budget cap, quality threshold, and batch multi-order chat requests need explicit domain contracts before becoming executable requirements. Current chat blocks unsupported constraints instead of silently approximating them.
- Automatic completion or due-date lapse is not implemented. Queue estimates and dates are predictions, not production event evidence.

## Handoff checks

```bash
git status --short --branch
uv run --no-sync python -X utf8 -m unittest discover -s tests -p "test_*.py" -q
node tests/test_chat_ui.cjs
node tests/test_ui_state.cjs
python -m demos.session_demo
```

Use a separate database for experiments and back up a real database before migration. An unchanged request ID is required for retry after an uncertain result; changed user input needs a new ID and a fresh recommendation. Inspect existing audit and checkpoints before repeating external actions. Do not rerun a full paid model evaluation to verify a documentation-only change.
