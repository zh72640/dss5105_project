# Dynamic Agent, Skills, tools, and business state

## Current and target mapping

| Existing component | Responsibility after this change |
| --- | --- |
| `app.services.chat` and `chat_*` SQLite tables | Session ownership, explicit confirmation, recommendation versions, transactionally saved business state, API compatibility, and the separate offline rules demo. |
| `app.offline.graph` and offline interpreter | Offline demo interpretation. They are not evidence of native model tool calls. |
| `app.agent.dynamic` | LangGraph model/tool loop, Skill snapshots, durable checkpoints, execution cap, wait state, and restart recovery for `llm` chat sessions. |
| `app.agent.skills` and `app/skills/*/SKILL.md` | Runtime Skill discovery and complete instructions loaded on model request. Business operation advice lives here. |
| `app.tools.registry` / `app.tools.operations` | Named, schema-described tools; validation and binding. Business handlers live in `app.services.agent_operations`. |
| `app.services.allocation_preflight`, `app.services.allocation`, `app.allocator` | Authoritative input checks; `allocate()` planning (`max_workshops`); solution validation; transactional allocation writes. |
| `app.allocator.scoring` | Original single-workshop timing and score formulas, called by `score_workshop`. |
| `app.services.lifecycle` | Audited, idempotent production event transaction, reused by the Agent production tool and `/events`. |

The user sends a message to the existing chat API. In an `llm` session the graph first shows the model the Skill catalog. The model requests `load_skill`, receives the exact Skill content and its permitted tool descriptions, then chooses subsequent tool calls. The tool node validates the loaded Skill, arguments, account scope, task state, and business facts. It executes the requested capability and returns a structured `{ok, data}` or `{ok: false, error: {code, message}}` result to the model. The model may call more tools, ask a question, or answer. It cannot set the task state directly.

All four configured providers use their LangChain chat model's native `bind_tools` method at the Agent call site. A backend without native tool-call support returns `TOOLS_UNSUPPORTED`; JSON text that looks like a plan is not executed. The offline rules mode is labelled as a demo and retains its existing behavior for compatibility.

## Skill catalog and Toolsets

Each `SKILL.md` has `name`, `description`, `triggers`, and `tools` front matter plus full instructions. The runtime reads the directory for every model prompt. Loading a Skill stores its full text and SHA-256 hash in the graph checkpoint. A completed turn clears its loaded Toolset before the next message, so the Agent must load the current Skill version and cannot retain withdrawn tool permissions. A turn resuming a pending question keeps the old snapshot even if the model requests `load_skill` again. There is no automatic migration of a paused task to revised instructions; the user can complete or cancel that task before starting a new one. Code and database guards remain in force for every version.

| Skill | Permitted tools |
| --- | --- |
| `order-inquiry` | `get_order`, `ask_user` |
| `workshop-inquiry` | `list_workshops`, `get_queue`, `score_workshop`, `ask_user` |
| `allocation-recommendation` | Order/workshop reads, `score_workshop`, `update_constraints`, `check_requirements`, `compute_plan`, `save_recommendation`, `ask_user` |
| `recommendation-explanation` | `inspect_recommendation`, order/workshop reads, `score_workshop`, `ask_user` |
| `constraint-revision` | `update_constraints`, `check_requirements`, `compute_plan`, `save_recommendation`, `ask_user` |
| `commit-and-production` | `inspect_recommendation`, `get_order`, `record_production_event`, `ask_user` |

Each call uses the schema in `app.tools.registry.TOOLS` (or `LOAD_SKILL`) and returns `{ok: true, data: ...}` or `{ok: false, error: {code, message}}`. The result payloads and principal refusal codes are:

| Tool | Inputs | Verified `data` | Principal refusal codes |
| --- | --- | --- | --- |
| `load_skill` | Skill name | Name, full instructions, permitted tools, content hash | `SKILL_NOT_FOUND`, `UNREGISTERED_TOOL` |
| `get_order` | Order ID | Registered order, state, version, remaining pieces | `ORDER_NOT_FOUND` |
| `list_workshops` | Optional workshop ID | Current workshop rows and aged queues | `WORKSHOP_NOT_FOUND` |
| `get_queue` | Workshop ID | Queue days and business date | `WORKSHOP_NOT_FOUND` |
| `score_workshop` | Workshop ID, order ID, optional batch pieces | Four original scores, inputs, and eligibility rejection | `ORDER_NOT_FOUND`, `WORKSHOP_NOT_FOUND`, `INVALID_QUANTITY` |
| `update_constraints` | Field, value, operation | Revised draft, task version, invalidation result | `INVALID_FIELD`, `UNGROUNDED_CHANGE`, `INVALID_TASK_STATE` |
| `check_requirements` | No arguments | Preflight report, facts hash, new task state | `INVALID_TASK_STATE` |
| `compute_plan` | No arguments | Checked integer split, report, facts and plan hashes | `PLAN_BLOCKED`, `INVALID_TASK_STATE` |
| `save_recommendation` | No arguments | Saved recommendation ID, task version, plan | `PLAN_REQUIRED`, `STALE_PLAN` |
| `inspect_recommendation` | No arguments | Saved recommendation and reconciled status | `RECOMMENDATION_NOT_FOUND` |
| `ask_user` | English question | Question saved for the next turn | `INVALID_ARGUMENTS`, `ENGLISH_REQUIRED` |
| `record_production_event` | Explicit action, order, version, reason, and action-specific fields | Lifecycle service result and audit event | `EVENT_NOT_AUTHORIZED`, `TOOL_NOT_ALLOWED`, lifecycle reason code |

Any tool can also return `TOOL_NOT_ALLOWED` when its Skill has not been loaded, or `INVALID_ARGUMENTS` when parameters violate its schema. Model supplied account identity and success flags are ignored.

Tool schemas are defined in `app.tools.registry.TOOLS`. The generic return envelope carries verified data or an error code and message; `chat_agent_tool_calls` records the full arguments, result, Skill hash, and state before and after each call. `chat_agent_events` records start, resume, pause, finish, errors, rejected calls, production results, and explicit confirmation outcomes. A confirmation event is written in the same transaction as its business result and includes the recommendation ID, versions, facts and plan hashes, and state transition. These are inspectable execution traces; no hidden model reasoning is needed.

An authenticated owner can review these records at `GET /api/chat/sessions/{session_id}/trace?limit=100`. The endpoint returns tool calls and events in execution order. For example, the tested recommendation path is `load_skill → update_constraints(order_id) → score_workshop → check_requirements(COLLECTING→READY) → compute_plan → save_recommendation(READY→RECOMMENDED)`. The confirmation button then moves the task to `CONFIRMED` in the existing chat transaction; a plain recommendation turn never does.

`score_workshop` is a thin adapter around the four restored functions in `app/allocator/scoring.py`. It loads a real `Workshop`, uses the aged queue returned by `workshop_repository.get_all`, uses a positive integer batch, converts the registered due date to a `date`, and uses the session business date as `sent_date`. The original formulas are unchanged:

- `get_estimated_completion_time`: `pieces / capacity + lead_days + queue_days`, in days.
- `get_lateness_score`: estimated days minus `(due_date - sent_date).days` for an active workshop; `10000` otherwise. Negative values indicate time before the deadline.
- `get_defect_score`: the workshop defect rate for an active workshop; `10000` otherwise.
- `get_hybrid_score`: defect rate if the original lateness score is nonpositive; `10000` otherwise.

These functions score a single workshop and batch. They do not enforce the full split, maximum batch, category, exclusion, capacity, or quantity conservation rules. The allocator planner's `hybrid` score is `0.6 * estimated_days + 0.4 * defect_rate * 100`; it is **not** equivalent to the original deadline-gated hybrid score. `score_workshop` exposes both its eligibility rejection and the original score semantics. Full recommendations continue to use `app.allocator.allocate` (split only when `max_workshops >= 2`) plus `check_solution`; no original formula was copied into a second implementation.

## State, authority, and transactions

The existing task states remain `COLLECTING`, `BLOCKED`, `READY`, `RECOMMENDED`, `CONFIRMED`, and `CANCELLED`. `ALLOWED_TASK_STATES` in the toolset maps mutations to their permitted source states. `check_requirements` calls the authoritative preflight before `READY`. `compute_plan` requires `READY` or a still valid `RECOMMENDED` task and verifies the solution. `save_recommendation` requires a plan computed in the current graph run, then recomputes under a SQLite write transaction and compares facts hash, plan hash, and task version before setting `RECOMMENDED`. A changed requirement increments the task version and supersedes the prior recommendation in the same transaction. Stale preflight or plan results demote the task and supersede the old recommendation.

The graph stores conversation messages, loaded Skill text/hash, pending question, current calculated plan, tool results, and step count. SQLite business tables are authoritative for task state, recommendation validity, order state, queue, and allocations. Every tool reloads the owner-scoped session from SQLite. The graph never treats a model-supplied `confirmed`, `committed`, or `valid` field as business evidence.

Final reply assembly also checks direct commitment and production-recording success claims against the saved task, recommendation, and tool result. If the model asserts such a success without evidence, the server replaces the sentence with a refusal. A Chinese question is refused with `ENGLISH_REQUIRED`; a Chinese final answer is replaced with an English continuation message. The response's `committed` flag and recommendation cards are always built from database facts.

`inspect_recommendation` and final response assembly reconcile a saved recommendation with current business facts in a database transaction. If it is stale, the recommendation is superseded and the task becomes `READY` or `BLOCKED` according to fresh preflight. A final Agent sentence claiming the old card is current is replaced with an explicit stale notice. The existing read-only session endpoint also hides stale cards without writing business state.

Only the explicit chat `confirm` action commits a recommendation. The service checks owner, session version, recommendation ID and task version, reruns planning against the latest order/workshop/queue facts, and calls `allocation.apply` inside the same transaction that records confirmation and audit. Preview and recommendation tools do not write `working_order` or queues. A message such as “confirm, but change quantity to 500” is a message turn: the change invalidates the old recommendation and cannot commit it.

`record_production_event` requires a loaded production Skill and current user words that explicitly state the action, order, and audit reason. Completion also requires the workshop and quantity in those words; supplied reassignment constraints must be grounded as well. Rejected calls are saved in the execution trace. The authenticated account supplies the actor; a stable server-generated event ID supplies idempotency. The tool delegates to `app.services.lifecycle.process_event`, which checks order version, legal production state, quantity, queue conservation, and database transaction rules. `/events` remains available.

## Wait and recovery

The system uses an explicit end-of-turn wait for user clarification or confirmation, not a LangGraph `interrupt` in the same turn. `ask_user` saves the pending question in the graph and returns it to the UI. The next chat message starts a new turn on the stable checkpoint thread `chat-agent:<session_id>`, preserving messages and the pinned Skill while clearing the old pending flag. Explicit confirmation stays an API action with a recommendation ID and expected session version.

The session version binds a reply to the latest pending question. Once `ask_user` succeeds in a batch of native model calls, subsequent calls in that batch receive `USER_INPUT_REQUIRED` and are audited without execution. The model cannot use a question as permission for another action before the user responds.

The graph uses the SQLite `SqliteSaver` checkpointer with synchronous durability. Each run has a unique request ID and a durable `chat_agent_runs` row. If execution stops mid-graph, retrying the **same** request ID resumes its saved node. A different request is rejected until that run is recovered. When an existing LLM chat session has saved messages but no Agent checkpoint, its latest saved user/assistant messages seed the graph once, preserving conversation context across the refactor. Tool calls have stable invocation keys `<request_id>:<native_tool_call_id>` and return their saved result on replay. Recommendation writes and tool-call records share a transaction. Production events have a stable derived event ID and their lifecycle service is idempotent even if the process exits after the event transaction but before the tool trace is saved. A checkpoint is never treated as an exactly-once guarantee or as user authorization.

The graph caps model steps at 12 and executable tool calls at 32 per turn. Extra tool calls receive an audited `EXECUTION_LIMIT` result; reaching the model-step cap returns a continuation message. Expected tool failures return structured errors to the model so it can query, revise, or ask the user. On restart, each tool rechecks the database before acting; stale graph snapshots cannot promote a task or submit an old plan.

## Verification

`tests/test_dynamic_agent.py` exercises native `bind_tools` on all four configured provider adapters, Skill permission gating, withdrawal of old permissions on a new turn, order lookup, the actual calls to all four restored formulas, recommendation generation without production writes, explicit commit and replay, illegal save rejection, wait and next-turn resume with a pinned Skill, requirement revision before attempted confirmation, stale card reconciliation, restart after a saved recommendation, production event actor and replay, refusal of actions following `ask_user`, a simulated process exit after a production transaction, unauthorized production arguments with an audit trace, and Skill file reload with a changed hash and newly enabled tool. The test model emits native `AIMessage.tool_calls`; it is a deterministic test double, not a live provider acceptance result. Live provider quality depends on configured credentials and has not been asserted by mocked tests.
