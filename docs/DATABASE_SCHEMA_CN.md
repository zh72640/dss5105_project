# Database mapping, transactions, and state semantics

The current SQLite schema is version 9. Migrations `001_initial.sql` through `009_agent_runtime.sql` are applied in order and recorded in `schema_migrations`. Migration 008 adds owner-scoped chat sessions, tasks, turns, messages, and recommendations. Migration 009 adds Agent runs, tool calls, and execution events. LangGraph `SqliteSaver` creates separate checkpoint tables in the same database for execution position; checkpoints are not authoritative business records. The original external “Data Schema2” DDL is not in this repository, so compatibility with that unspecified schema has not been asserted.

## Tables and authority

| Table | Purpose |
| --- | --- |
| `schema_migrations` | Applied migration versions; unknown future versions stop startup. |
| `orders` | Imported order master data plus source status, business state, version, and completed quantity. |
| `workshops` | Capacity, pickup lead, defect rate, cost, eligibility categories, status, and batch limit. |
| `workshop_queue` | One row per workshop with current queue, baseline queue, and queue business date. |
| `working_order` | Active order/workshop pieces, completed pieces, capacity at assignment, and unconsumed queue reservation. |
| `unassigned_order`, `completed_order`, `lapsed_order` | No feasible assignment, completed production, and explicit lapse records. |
| `requests`, `request_parsing_history`, `decision_log`, `request_actors` | Request idempotency, validated parse or merged draft, decision evidence, and approved actor. |
| `lifecycle_events` | Audited production action with actor, reason, expected version, applied flag, and before/after snapshots. |
| `sessions`, `session_messages` | Legacy `session_v1` allocation draft, version, blockers, and ordered user/assistant turns. |
| `desk_users`, `login_sessions` | Salted account password hashes, roles, and hashed expiring login tokens. |
| `jobs` | Background session revisions, idempotency fingerprint, status, attempts, lease, retry time, and result. |
| `chat_sessions`, `chat_allocation_tasks` | Owner-scoped current chat conversation and deterministic task state/version. |
| `chat_turns`, `chat_messages` | Durable chat turns, request fingerprint, response, and ordered messages. |
| `chat_recommendations` | Versioned recommendation, validity status, plan and facts hashes, and actual confirmation result. |
| `chat_agent_runs` | Agent request ID, session, fingerprint, expected version, and run status for crash recovery. |
| `chat_agent_tool_calls` | Stable invocation key, Skill hash, tool name/arguments/result, and state before/after. |
| `chat_agent_events` | Start, resume, tool result, refusal, wait, finish, and execution error trace. |
| LangGraph checkpoint tables | Agent messages, loaded Skill snapshots, pending question, computed plan, and graph execution progress. |

The queue has one authoritative record in `workshop_queue`; repository joins attach it to workshop query results. The application does not maintain a second independent queue value in `workshops`.

## Order states and allocation rules

| Order state | Meaning | New allocation |
| --- | --- | --- |
| `READY` | Unfinished source order or an order whose remaining assignment was cancelled. | Allowed. |
| `WORKING` | Active assignment with queue reservation. | Refused to avoid double counting. |
| `UNASSIGNED` | Valid request but no feasible allocation. | Allowed with a new request ID. |
| `COMPLETED` | Imported as complete or fully completed by production events. | Refused. |
| `LAPSED` | Explicitly terminated by a lapse event. | Refused. |

Imported source `IN_PROGRESS` orders begin as `READY`: the source status does not prove this application has allocated them. Past due dates do not automatically lapse an order. Normally the due date is a planning target and lateness creates a warning; only `deadline_required=true` makes it a hard constraint.

The authoritative order lookup is an exact order ID. A stated customer, product, category, quantity, order date, or due date that contradicts registered data produces a conflict and does not edit the order. A missing or ambiguous ID asks for clarification.

Eligibility checks exclusion, `ACTIVE` status, category capability, batch limit, and positive capacity. With one workshop, that workshop must accept the entire remaining batch. With multiple workshops, each split must satisfy its own maximum batch. A preferred workshop must accept the whole order; the planner does not silently split or substitute it. A workshop count is an upper bound, not an exact count.

The current planner uses integer pieces and checks quantity conservation. `min_cost` and `min_defects` optimize the corresponding per-piece measures. `min_delay` minimizes the last completion among selected workshops. Its `hybrid` heuristic uses `0.6 * estimated_days + 0.4 * defect_rate * 100`; it is distinct from the deadline-gated `get_hybrid_score` restored in `app/tools/allocation.py`. Full-plan correctness is checked after planning. Production queue additions use processing time `pieces / capacity`, not pickup lead. Estimates include queue, processing, and pickup lead. The UI rounds displayed dates upward; external simulators may round differently.

## Parser history and transactions

`request_parsing_history` stores parser fields such as order ID, customer, product, category, pieces, order/due dates, objective, exclusion, allowed workshop count, preferred workshop, deadline requirement, parse status, missing fields, and ambiguities. Server-provided request ID, timestamp, and original message are recorded separately. Missing parsed fields remain null; later database enrichment appears in the decision trace, not as invented parser output.

The legacy direct allocation pipeline parses before taking a SQLite write lock. Under `BEGIN IMMEDIATE`, it rechecks the request ID and writes request, parse history, decision, active assignments, queue, order state, and unassigned cleanup together. The same ID with the same fingerprint replays the saved result. Reusing an ID for changed input conflicts. A new ID cannot allocate a `WORKING` order again.

The original session API commits draft messages and an explicit approval atomically with any resulting business write. The current chat API similarly commits confirmation, recommendation status, allocation, queue, audit, and feedback in one transaction. Recommendation and preview writes do not touch production allocation or queue. A stale recommendation is superseded; the Agent must compute and save a new one before confirmation. The database transaction result, not graph state or Agent text, determines success.

Lifecycle events preserve completed quantity and account for FIFO queue decay; see [production lifecycle](LIFECYCLE_CN.md). A failed SQL transaction rolls back all business effects. If a best-effort error audit cannot be saved, the response reports that limitation instead of claiming a durable log.

## Migration and recovery

Opening an older supported database applies unapplied migrations transactionally. Migrations do not reimport CSV data or reset current queues. Back up a production database and verify a copy before upgrading. Do not manually remove `working_order` rows to reset a demo: order state and queue reservations must change together. Use a separate database path for demos.

Background jobs recover expired worker leases using the persisted job ledger. Dynamic Agent turns use `chat_agent_runs` and SQLite LangGraph checkpoints: retry the same request ID to resume an interrupted run. The graph may execute a tool node again after a crash, so each business write also has a stable idempotency key and verifies the database facts. Production lifecycle events remain safe if the process stops after their transaction but before the graph trace is saved. A resumed graph never grants user confirmation or permission by itself.
