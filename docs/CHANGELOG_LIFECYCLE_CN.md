# MVP v0.2 lifecycle delivery and acceptance

Historical date: 2026-10-02. This work began from commit `2207f29` on the original `ningtao` branch. Commit `bb02527` recorded real Gemini acceptance and rate-limit classification; `c84be0f` added migration 002, partial completion, cancellation, lapse, atomic reassignment, FIFO reservations, versions, audit, and 27 focused tests; `e93af25` added UI, HTTP, CLI, and an end-to-end lifecycle demo. Later repository restructuring moved several original file paths into service and tool packages. This record describes what those commits delivered, not the current file layout.

## Delivered behavior

- Migration `002_lifecycle.sql` added order version and completed quantity, assignment queue reservations, and lifecycle audit.
- Production actions include inspect, complete, cancel, lapse, and reassign. They check order version, quantity and legal state, use idempotent event IDs, preserve historical snapshots, and commit business changes with audit.
- FIFO queue decay consumes baseline work first, then reservations. Cancelling releases only unconsumed reserved time; partial completion does not subtract elapsed capacity twice.
- The direct allocation pipeline began assigning only unfinished pieces and incrementing order versions. The UI and HTTP API exposed order inspection and production events, with a CLI and isolated demonstration.
- Tests covered state, quantity, queue, concurrency, failure injection, migration, real HTTP routes, and CLI process behavior.

The original delivery also updated the lifecycle, database, system, schema, and next-stage documents; `evaluation/results/lifecycle_demo.json`, `parser_llm_metrics.json`, the verification summary, and release manifest recorded acceptance evidence. Original data, official simulator harness and baselines, Week 4 fixtures, Parser/Prompt v1, migration 001, and dependency versions were preserved at that release. Runtime databases, credentials, virtual environments, and raw provider error bodies were not committed.

## Historical verification

`evaluation/verify_mvp.py` passed **150 tests, 0 failures, 0 errors, 0 skips** at this release. Its additional coverage included 27 lifecycle/migration tests, two evaluation tests, three HTTP/UI checks, and one CLI test. The offline parser matched 60/60 golden cases; 30/30 original behavior labels matched. The official standard/shock simulator output matched the historical baseline, without a claim that the new allocator was superior.

The lifecycle demo passed queue conservation, foreign keys, and replay checks. A Chrome check against an isolated temporary database allocated 150 pieces of `ORD-045` to W6, completed 50, reassigned 100 to W8, refreshed, then completed the remaining 100. The final state was `COMPLETED`, 150/150 complete, zero remaining, version 4, with visible history.

The Gemini smoke test succeeded, but the full 60-case run had 14 matching outputs and 46 final HTTP 429 cases, with 91 total 429 and six 503 attempts. The full live acceptance failed. Missing outputs cannot be counted as model field errors or removed from the denominator to claim a pass; see the [live acceptance record](GEMINI_LIVE_ACCEPTANCE_CN.md).

Unresolved external items at that time were the missing original Data Schema2 DDL, business-policy confirmation, a second human label review, and an independent holdout. The current project has since added legacy sessions, accounts, jobs, chat v2, and a native-tool Agent. For current behavior use the [system guide](SYSTEM_GUIDE_CN.md) and [architecture guide](AGENT_SKILL_ARCHITECTURE.md).
