# Chat v2 user and developer guide

The standalone chat is at `/chat` and shares recommendation confirmation with the workbench. It uses FastAPI, LangGraph, SQLite, the configured model registry, and the existing deterministic allocation planner. The current database schema is version 9; upgrades preserve earlier orders, accounts, sessions, and assignments.

## Start and select a mode

```bash
uv run --locked python -m app.server --backend offline
```

Open `http://127.0.0.1:8000/chat` and sign in with an existing account. New sessions can select the offline rules demo or a configured `llm` model. The chosen mode and model stay fixed for that session. Supply provider credentials through the existing environment configuration, for example `uv run --env-file .env ...`. The offline demo is separate from the native-tool Agent and does not prove live tool calling.

## Allocation flow

1. Create a request and describe the needed allocation. The Agent can ask for a missing order ID instead of assuming one.
2. For an LLM session, the Agent sees the Skill catalog, loads a relevant application Skill, and requests permitted tools for order/workshop facts, score calculations, preflight, full planning, or clarification.
3. A passing preflight and checked plan can be saved as a recommendation card. A card is a proposal; it does not update production assignments or queues.
4. Ask why a workshop was selected, revise a constraint, or request fresh facts. A plan-affecting revision supersedes the old card. The Agent can use an existing valid recommendation for explanation.
5. Confirm by clicking the card's action in chat or the workbench. The request must name the exact recommendation ID and current session version. The server rechecks authorization, task version, order/workshop/queue facts, and the plan before one atomic allocation transaction.
6. A successful confirmation stores the actual allocation and feedback in that recommendation's session. The session remains readable and can later be archived. Use a new session for another order.

For `llm` sessions, ordinary message text cannot submit production allocation. “Confirm, but use 500 pieces” is processed as a requirement change; it invalidates the old card and requires a new recommendation and explicit confirmation. A production lifecycle event is a separate, explicitly authorized action through the production Skill or existing event API.

## Two entry points and concurrency

Chat and the workbench use the same recommendation ID and confirmation service. A result appears in the recommendation's own session, even if another session is currently selected in the browser. The service binds confirmation to the owner, recommendation ID, task version, session version, and current business facts. Competing confirmations cannot allocate twice. On an uncertain network result, the browser retains the original request ID and retries it rather than creating a new operation.

The browser restores recent session selection per account. Server records remain authoritative for messages and recommendations. Refresh and polling update both entry points, but server transaction checks protect against a stale card even before the UI notices the change.

## Agent wait and recovery

When information is missing, `ask_user` saves a pending question and ends the current graph turn. The user's next message starts a new turn on the same stable checkpoint, preserving messages and the pinned Skill version. A completed turn clears its loaded Toolset so a later turn must load current Skill permissions. A service restart or uncertain execution is resumed with the same request ID from SQLite checkpoints and the Agent run ledger. Each mutating tool also has a stable idempotency key, because LangGraph can replay a node.

The Agent's tool failures and state transitions are available to the session owner at `GET /api/chat/sessions/{id}/trace`. Its text cannot serve as evidence of a confirmed assignment: the response's `committed` flag and card status derive from saved business facts.

## API and code locations

| Location | Purpose |
| --- | --- |
| `app/schemas/chat.py` | Strict HTTP input, action, version, and recommendation ID validation. |
| `app/agent/skills.py`, `app/skills/*/SKILL.md` | Runtime Skill discovery, content snapshots, and Toolset permissions. |
| `app/agent/dynamic.py`, `app/services/agent_chat.py` | Native model/tool loop, checkpoint and request recovery, Agent audit. |
| `app/agent/toolset.py` | Named business tools and state guards. |
| `app/services/allocation_preflight.py`, `app/services/allocation.py` | Requirement checks, solution verification, and atomic assignment. |
| `app/tools/allocation.py`, `app/tools/allocator/planner.py` | Restored original single-workshop scores and the existing full split planner, respectively. |
| `app/services/chat.py`, `app/tools/database/chat_repository.py` | Owner-scoped sessions, recommendations, explicit confirmation, replay. |
| `app/api/routes/chat.py`, migrations 008 and 009 | HTTP and durable tables. |
| `app/ui/chat.html`, `chat.css`, `chat.js`, `chat-common.js`, and `desk-chat.js` | Standalone and workbench UI adapters. |

See the [UI guide](UI_GUIDE_CN.md) for use of both entry points. The precise routes and error behavior are in [HTTP API](UI_API_CN.md).

The task supports one order per chat session. Unsupported hard constraints such as a budget cap, exact split, or quality threshold must be clarified or withdrawn; they are not silently approximated. Registered master data cannot be edited from chat. No streaming response or chat search is currently provided.

The dynamic Agent acceptance tests use scripted native `AIMessage.tool_calls` to verify real graph execution, tool guards, persistence, and transactions. They do not establish live provider quality. Earlier offline evaluation scripts and browser checks are separate evidence.
