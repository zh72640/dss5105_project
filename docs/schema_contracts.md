# Week 4 schema contracts (v0.1 frozen)

These contracts are frozen for Week 4 integration. Additive changes require a
version bump; renaming or changing field meaning requires team review.

## StructuredRequest

Producer: M1 parser. Consumers: M2 conversation, M3 tools, M4 allocator.

Required contract fields: request/order identity, customer, product/category,
quantity, ISO required date, preferred/excluded workshop, objective override,
constraints, missing/ambiguous diagnostics, and raw text.

## CandidateMetrics

Producers: M3/M4 deterministic tools. Consumers: M4/M5/M6.

Includes workshop identity, eligibility and exact exclusion reason; queue,
processing, transport and turnaround days; cost and defect rate; estimated ISO
delivery date and deadline result; optional configured score.

## AllocationResult

Producer: M4/conversation gate. Consumers: M5 UI, M6 evaluation, audit log.

Includes decision status (`ALLOCATE`, `CLARIFY`, `REFUSE`, `DECLINE`, or
`ESCALATE`), recommendation, complete eligible ranking, reason codes, configured
objective, warnings, and a human-facing message.

## Failure rules

- Missing/ambiguous identity: `CLARIFY`, never guess.
- Unsupported data question: `DECLINE`, never invent.
- Ineligible preferred workshop: `REFUSE` with exact hard-rule reason.
- No eligible candidate: `ESCALATE` with options added in a later iteration.


## Week 5/6 migration note (2026-09-14)

The contracts above remain the **historical Week 4** contracts. The active entry
point for offline seeding is `app.services.dispatch.seed_allocation()` (Chat v2 owns HTTP allocation)
with `parsed`, `parser_telemetry`, `trace`, and `result`. The new frozen ParseResult
lives in `app/schemas/parser_schema.py` (shared draft/recommendation shape; Parser v1 HTTP was retired).

Week 4 schemas, fixture parser and CSV allocation tools were retired on 2026-10-14. The frozen definitions above remain documentation of the historical contract. Current code uses ParseResult and SQLite-backed services; `result` includes integer allocation parts, success/status, rejection reasons and queue/database traces.

## MVP v0.2 addition (2026-10-02)

The contracts above are historical. The allocation entry point retained Parser/Prompt v1 and returned mvp_v0.2. Migration 002 added accumulated completion, order versions, FIFO queue reservations, and lifecycle events. `app.services.lifecycle.process_event()` provides a separate structured production operation; see the [lifecycle guide](LIFECYCLE_CN.md). The remaining active assignment pieces plus confirmed completed pieces are conserved; after partial completion, active assignment rows alone no longer sum to the original order total.

### MVP v0.3 session addition (2026-10-03)

The release became mvp_v0.3 while the direct allocation envelope stayed mvp_v0.2 for idempotency compatibility. Migration 003 added `sessions` and `session_messages`; the independent session_v1 API supports messages, full replacement, confirmation, and closure. Parser v1 remains a single-message contract. The session layer explicitly merges follow-up fields and audits the whole conversation as evidence. See [sessions](SESSIONS_CN.md) and [database mapping](DATABASE_SCHEMA_CN.md).

## MVP v0.4 UI and authentication addition (2026-10-06)

Migration 004 added accounts, hashed login tokens, and request actors without rewriting prior migrations. HTTP business calls require login by default and receive their actor from server authentication. The actor enters the idempotency fingerprint. Recommendation rejection remains an explicit message command rather than a new legacy session action. Dashboard, workshop, audit, and export endpoints are read-only; see [HTTP API](UI_API_CN.md).

## MVP v0.5 addition (2026-10-09)

The DeepSeek backend reads its key from the server environment. Authenticated `GET /api/ai/status` returns only backend, configured flag, and model. A legacy session turn can accept validated structured `changes` only for an empty `message` action; it merges the draft without invoking a model, and the canonical edit enters the idempotency fingerprint and audit. A bound order cannot be replaced by another order. `assistant_reply` and `clarifications` provide a grounded summary and specific questions. Dashboard and audit gained allocation summaries; old records are not rewritten.

## Current dynamic chat addition (2026-10-15)

Migrations 008 and 009 add owner-scoped chat sessions/recommendations and the durable Agent run/tool/event ledger. LLM chat uses native model tool calls, runtime application Skills, deterministic state guards, and persisted LangGraph checkpoints. These are separate from the frozen Week 4 and legacy session_v1 contracts. The explicit chat `confirm` action commits only a named, current recommendation; message text and model output cannot act as confirmation. See [dynamic architecture](AGENT_SKILL_ARCHITECTURE.md).
