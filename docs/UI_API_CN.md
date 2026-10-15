# HTTP API for the dispatch UI

FastAPI serves the API at `http://127.0.0.1:8000` by default. Interactive documentation is at `/docs`; the machine contract is `/openapi.json`. Writes require JSON and a permitted Origin. Except for static resources, health, login, and `auth/me`, business endpoints require login. Accounts share the underlying order and workshop workspace, while chat v2 sessions are owner-scoped.

## Authentication and status

| Method and endpoint | Result |
| --- | --- |
| `GET /api/auth/me` | Username, role, authentication requirement, and setup requirement. An unauthenticated username and role are null. |
| `POST /api/auth/login` | Username/password login; sets an HttpOnly, SameSite=Strict cookie. |
| `POST /api/auth/logout` | Revokes the server token and clears the cookie. |
| `GET /api/health` | Status, backend, business date, application and pipeline versions. |
| `GET /api/ai/status` | Configured backend and model, without credentials or environment contents. |

Login sessions last eight hours. Ordinary accounts are created or reset through `python -m app.cli.auth USERNAME --db PATH`; the migration provisions the reserved administrator. Role checks use the database, and admin-only endpoints reject ordinary accounts. Failed login and request validation have distinct responses. `--no-auth` is an explicit local demo mode using a demo identity, not a production account.

## Read endpoints

| Method and endpoint | Main result |
| --- | --- |
| `GET /api/dashboard` | Statistics, inbox, orders, workshops, business date, UTC audit date, and recent allocations. |
| `GET /api/workshops?q=&status=&category=` | Filtered workshop rows and business date. Name/ID search is a substring; status and category match exactly. |
| `GET /api/audit?q=&status=&page=1&page_size=25` | Paged request audit, with page size 1–100. |
| `GET /api/audit/{request_id}` | Full decision record or 404. |
| `GET /api/audit/export?format=json` or `csv` | Full export, independent of page filters. CSV uses UTF-8 BOM and protects formula-like cells. |
| `GET /api/orders/{order_id}` | Order state, version, allocations, and lifecycle history. |
| `GET /api/history` | Legacy summary of the latest 30 entries; use audit export for all records. |

Workshop entries include capacity, lead days, defect rate, cost, product categories, status, batch limit, queue days, notes, and unfinished assigned pieces. Dashboard counters describe different populations and cannot simply be added to derive a total order count.

## Current chat API

The standalone `/chat` page and the workbench recommendation panel use the same recommendation ID and confirmation endpoint. A chat session stores its selected mode and model, task, messages, recommendation, and version. The server, not the model, supplies account identity.

| Method and endpoint | Purpose |
| --- | --- |
| `POST /api/chat/sessions` | Idempotent creation; requires `request_id`, with optional initial message, objective, mode, and model key. |
| `GET /api/chat/sessions` | Owner-scoped session list with cursor pagination. |
| `GET /api/chat/sessions/{session_id}` | Current owner-scoped session and recommendation validity. |
| `GET /api/chat/sessions/{session_id}/messages` | Paginated message history. |
| `GET /api/chat/sessions/{session_id}/trace?limit=100` | Owner-scoped Skill, tool, state, wait, retry, and rejection events. |
| `GET /api/chat/recommendations` | Owner-scoped recommendations, optionally filtered by status. |
| `POST /api/chat/sessions/{session_id}/turns` | Message, new request, explicit confirmation, or archive. Requires `request_id` and `expected_version`. |

Example message:

```json
{"request_id":"chat-turn-1","expected_version":0,"action":"message","message":"Recommend an allocation for ORD-045."}
```

Confirmation uses `action="confirm"`, an empty message, the exact `recommendation_id`, and the current `expected_version`. The service checks account scope, recommendation/task versions, current business facts, and the final allocation within one transaction. A conversational sentence that also changes constraints is a message turn and cannot confirm the old card. `committed=true` appears only after the transaction succeeds.

For an `llm` session, a message starts the native-tool Agent. The Agent may return `pending_question` and end its turn. The next message resumes on the same persisted graph checkpoint. Retrying an interrupted request uses the same request ID. If the model backend does not support native calls, the endpoint returns `TOOLS_UNSUPPORTED`.

## Other writes

`POST /api/events` handles explicit production events. Authenticated HTTP calls derive the actor from login rather than trusting a client actor field. The local CLI has separate filesystem and audit-label semantics.

**Retired:** `POST /api/requests` (Parser v1), `/api/sessions*` (legacy multi-turn), and `/api/jobs` (`session_revise`). Conversational allocation uses Chat v2 above; Desk new-request actions redirect to `/chat`.

## Errors and retries

Bad fields and JSON types return 400, unauthenticated business access 401, a disallowed Origin or insufficient role 403, missing resources or inaccessible chat sessions 404, version/idempotency/stale recommendation conflicts 409, unsupported content type 415, excessive body size 413, and unavailable model/database service 503. A 200 response can still describe a clarification or refused business decision; inspect `committed` and the result rather than treating HTTP success as allocation success.

On an uncertain network result, retry with the same request ID or lifecycle event ID and unchanged input. Creating a new ID could repeat a successful operation. An existing ID with changed input is rejected. Static assets are served from an allowlist, not arbitrary filesystem paths.
