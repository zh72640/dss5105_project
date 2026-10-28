# Dynamic Agent acceptance

This record covers the implementation in [Dynamic Agent architecture](AGENT_SKILL_ARCHITECTURE.md). It separates production graph/tool behavior exercised with scripted native model calls from a live provider acceptance, which has not been completed in this workspace.

## Reproducible execution trace

Run:

```bash
uv run --no-sync python -X utf8 -m evaluation.verify_dynamic_agent
```

The script creates an isolated temporary SQLite database, submits native `AIMessage.tool_calls` through the production LangGraph, tools, and services, then writes [the complete trace](../evaluation/results/dynamic_agent_acceptance.json). No user runtime database is modified. The trace includes Skill names and SHA-256 hashes, offered tools, call arguments and verified results, task states before and after, start/wait/resume/finish events, recommendation ID, and final database facts.

Observed path:

```text
order question
  load_skill(order-inquiry) -> get_order
allocation request
  load_skill(allocation-recommendation) -> update_constraints(order_id)
  -> score_workshop -> check_requirements(COLLECTING to READY)
  -> compute_plan -> save_recommendation(READY to RECOMMENDED)
constraint revision
  load_skill(constraint-revision) -> update_constraints(objective)
  -> old card superseded -> check_requirements -> compute_plan
  -> save_recommendation(new RECOMMENDED card)
explicit confirm action
  RECOMMENDED to CONFIRMED, one production assignment transaction
production request
  load_skill(commit-and-production) -> get_order -> record_production_event
missing-information request
  load_skill(allocation-recommendation) -> ask_user -> wait
next message
  pinned Skill snapshot -> get_order -> finish
```

The acceptance run observed zero `working_order` rows after both the initial and revised recommendations, the old card marked `superseded`, `committed=true` after the explicit confirm action, a replayed confirmation with no second allocation, one completed production event, and a pending question cleared on the next message. Querying an order offered only `load_skill` initially and then the loaded inquiry Toolset.

## Behavioral checks

| Requirement | Evidence |
| --- | --- |
| Runtime Skill discovery and actual loading | `tests.test_dynamic_agent.test_skill_catalog_is_runtime_loaded`, query/recommendation traces, loaded Skill hash in `chat_agent_tool_calls`. |
| HTTP to native graph and owner-scoped trace route | `test_authenticated_http_chat_turn_uses_native_tool_graph_and_trace` posts a real FastAPI chat turn, checks offered native tools and the `GET /trace` response. |
| Native tool calling, not JSON-plan execution | `test_model_registry_uses_native_bind_tools`, `test_configured_provider_adapters_accept_native_tool_schemas`; the graph consumes `AIMessage.tool_calls`. A backend without that interface returns `TOOLS_UNSUPPORTED`. |
| Query, clarification, calculation, explanation | Order query and missing-info tests; recommendation trace; saved-card inspection and stale-card reconciliation tests. |
| Restored `allocation.py` reuse | `test_recommendation_scores_and_commits_once` wraps all four original functions and checks ETA, lateness, defects, and deadline-gated hybrid outputs. `test_inactive_workshop_uses_original_score_sentinels` checks the three 10000 refusal scores. |
| State and transaction guards | Illegal recommendation save, ungrounded requirement, unauthorized production arguments, false model success claim, stale queue, revised quantity with “confirm,” owner/version checks, and rollback tests. A valid objective revision supersedes the old card, saves a new preview, and still writes no production assignment. |
| Explicit confirmation and queue safety | The trace has no assignment at recommendation time. Confirmation and replay tests check one business transaction, fresh facts, and no duplicate queue write. The same transaction records `confirmation_committed` with its evidence; a changed queue produces `confirmation_stale` and no allocation. An injected confirmation-trace write failure rolls back assignment and queue changes, then the same request ID succeeds after repair. |
| Tool failure recovery | The model receives structured refusal and can call `ask_user`; calls after a pending question in the same batch receive `USER_INPUT_REQUIRED`. |
| Execution bounds | At most 12 model steps and 32 executable tool calls per turn; an extra call receives an audited `EXECUTION_LIMIT` result. |
| Wait and Skill version policy | Waiting question resumes with its original Skill hash. A completed turn clears loaded permissions; a changed Skill is loaded on a later turn without Python workflow changes. |
| Existing LLM chat compatibility | A pre-Agent session with saved user/assistant messages and no checkpoint seeds those messages into the first dynamic graph turn. |
| Crash and retry | Tests interrupt after recommendation save and after lifecycle transaction; same-request retry resumes from SQLite checkpoint and does not repeat recommendation, production event, or queue update. |
| English output | A Chinese clarification question receives `ENGLISH_REQUIRED`; a Chinese final model reply is replaced with an English continuation. UI, runtime Skill files, prompts, tool descriptions, and new docs are English. |
| Auditable trace | `GET /api/chat/sessions/{id}/trace` is owner-scoped; it returns tool calls and events without hidden model reasoning. |

The scripted model establishes that the real graph and business tools execute native tool-call messages under the configured contracts. It does **not** establish that a paid provider will choose the right Skill or recover gracefully from every real response. Adapter schema binding was checked locally for OpenAI, Claude, Gemini, and DeepSeek. A live provider call attempted during this work could not complete because the network could not resolve the provider host, so no live end-to-end result is claimed.

## Regression commands

```bash
uv run --no-sync python -X utf8 -m unittest tests.test_dynamic_agent -q
uv run --no-sync python -X utf8 -m unittest discover -s tests -p "test_*.py" -q
node tests/test_chat_ui.cjs
node tests/test_ui_state.cjs
```

The focused dynamic-Agent suite passed **28 tests**. The complete Python regression passed **353 tests**, and the frontend suites passed **6 and 11 tests**. Failure-injection tests intentionally log caught SQLite exceptions while passing their rollback assertions.
