# Application architecture

This page keeps its historical filename for existing links. The current Agent design is specified in [Dynamic Agent, Skills, tools, and business state](AGENT_SKILL_ARCHITECTURE.md).

## Runtime boundaries

- `app/main.py` builds the FastAPI application. `app/api` owns routes, authenticated dependencies, and HTTP error handling. `app/core/lifespan.py` initializes configuration, the database, model registry, checkpoint support, and background workers.
- `app/services/chat.py` owns session compatibility, owner checks, explicit recommendation confirmation, idempotency, and the transaction that commits an allocation. LLM message turns use `app/services/agent_chat.py`; offline rules mode remains a separate demonstration path.
- `app/agent/dynamic.py` runs the LangGraph model and tool loop. It loads the application Skill catalog, offers tools allowed by loaded Skill snapshots, records tool results, and persists progress with a SQLite checkpointer. It never treats model text as a business state transition.
- `app/skills/*/SKILL.md` contains the business instructions for order and workshop inquiry, recommendation, explanation, revision, confirmation, and production. The running Agent discovers and loads these files; editing their instructions changes the next eligible load without changing Python orchestration.
- `app/agent/toolset.py` defines native-call tool schemas and guards. Reads use the existing database repositories. Workshop scores call all four restored functions in `app/tools/allocation.py`. Full split planning remains in `app/tools/allocator/planner.py` with service-level preflight and solution checks.
- `app/services/allocation.py` and `app/services/lifecycle.py` own business transactions. Preview and recommendation never write production allocations. Confirmation verifies the saved recommendation and current facts in a transaction. Production events use a stable idempotency key and their established audit and queue rules.
- `app/db` owns SQLite setup, schema migrations, and transaction helpers. The database is authoritative for orders, workshops, queues, task states, recommendations, commitments, and production events. LangGraph checkpoints hold execution progress and cached context, not independent business truth.

## Execution and recovery

A user message enters the existing chat API. In LLM mode, the Agent receives the Skill catalog and the current owner-scoped database snapshot. The model calls `load_skill`, then chooses among the Skill's available tools. Every tool request is checked for permission, schema validity, state, and current business facts. The model can continue, ask a question, or finish. A question ends the turn; the next message uses the same session thread and expected session version. A process restart resumes a pending node from the SQLite checkpoint using the same request ID. Side-effecting tools remain idempotent because checkpoint recovery may rerun a node.

The offline parser and older conversation router remain for compatibility and demonstrations. Their fixed interpretation path is not evidence of dynamic native tool selection. A configured model without native tool-call support is rejected with `TOOLS_UNSUPPORTED`.

## Audit and verification

`GET /api/chat/sessions/{session_id}/trace` exposes owner-scoped Skill names and hashes, tool arguments and results, state changes, and pause or resume events. `tests/test_dynamic_agent.py` checks query, recommendation, revision, confirmation, stale data, illegal calls, provider tool binding, and restart behavior. See the linked architecture document for tool contracts, formula semantics, state transitions, and test boundaries.
