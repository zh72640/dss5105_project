# Production lifecycle and manual operations

This guide describes the order lifecycle introduced in migration 002 and the current authenticated HTTP behavior. The assignment parser continues to handle allocation requests; production events use an explicit structured action. The dynamic chat Agent can request the same lifecycle service through its production Toolset when the user's current message authorizes the event.

## Actions and quantity rules

| Action | Required order state | Result |
| --- | --- | --- |
| `complete` | `WORKING`, with an active assignment at the named workshop | Adds the newly completed pieces. The order remains `WORKING` until all pieces are complete, then becomes `COMPLETED`. |
| `cancel` | `WORKING` | Releases remaining assignments and returns the order to `READY`. Previously completed pieces remain recorded. |
| `reassign` | `WORKING` | Replans all remaining pieces under the supplied constraints. Failure preserves the original assignment and queue. |
| `lapse` | `READY`, `UNASSIGNED`, or `WORKING` | Ends further production, releases remaining reservations, and sets `LAPSED`. |

`cancel` cancels the current assignment; `lapse` makes the order ineligible for future allocation. Neither elapsed queue time nor the due date automatically completes or lapses an order. A completed or lapsed order cannot be reopened through these actions.

`orders.pieces` is the registered total. `completed_pieces` is the acknowledged completed total. Reassignment handles `pieces - completed_pieces`; a completion event cannot exceed the remaining quantity at its named workshop. For example, completing 50 of 150 assigned pieces, cancelling, and assigning again leaves 100 pieces to plan.

## Transaction, replay, and audit

Each service event requires `action`, `order_id`, `actor`, `reason`, `expected_version`, and `event_id`. The authenticated HTTP route supplies the actor from the account, regardless of a client actor field. The dynamic Agent production tool also obtains the actor from its authenticated context and derives a stable event ID from the request and native tool call. Local CLI callers provide their own actor label; that label alone does not authenticate an account.

- The service verifies the current order version and action-specific state before writing. A successful allocation, applicable event, or transition to `UNASSIGNED` increments the order version; a rejected event does not.
- Replaying the same `event_id` with the same arguments returns the recorded result. Reusing that ID with different arguments returns `IDEMPOTENCY_CONFLICT`. Allocation request IDs and lifecycle event IDs share an idempotency namespace.
- A new ID carrying an old version returns `VERSION_CONFLICT`. Read the order again before deciding on a fresh action.
- Order, active assignments, queue, completion/lapse rows, request and decision records, and lifecycle audit are committed in one SQLite write transaction. A reassignment that cannot finish rolls back to the original assignments and queue.
- `lifecycle_events` retains actor, reason, business date, expected version, applied flag, and before/after snapshots. Even after an active assignment is removed, its history remains traceable. A business rejection is audited with `applied=0`; if audit insertion also fails, the transaction rolls back.

## Queue accounting

`workshop_queue.baseline_queue_days` records capacity already occupied outside the application's assignments. Each active `working_order` stores `queue_remaining_days` and `capacity_at_assignment`. The workshop queue is baseline plus the remaining active reservations.

Elapsed calendar days consume baseline first, then assignment reservations in insertion order. Cancelling or reassigning releases only the reservation that has not already elapsed. Partial completion caps a reservation against the remaining pieces and capacity at assignment. Transport lead time contributes to delivery estimates but not to the production queue.

Queue estimates are not proof of completion. A `complete` event is still required when predicted queue time reaches zero. A business-date rewind, missing queue row, or disagreement between total queue and components blocks the event. UTC audit timestamps and the service's configured business date are stored separately.

## Python, HTTP, and CLI

```python
from app.services.lifecycle import inspect_order, process_event

order = inspect_order("ORD-045", db_path="runtime/dispatch.sqlite3")
response = process_event(
    "complete", "ORD-045", workshop_id="W6", pieces=50,
    actor="operator-a", reason="Workshop confirmed the first batch",
    expected_version=order["version"], event_id="production-045-001",
    db_path="runtime/dispatch.sqlite3",
)
```

`reassign` can receive `objective`, `exclusion`, `max_workshops` (1–8), `preferred_workshop`, and `deadline_required`. Its defaults are fastest delivery, one workshop, and a soft deadline. It is a complete new constraint submission; a previous request's hard constraints must be supplied again when needed.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/orders/{order_id}` | Current state, version, active assignments, and recent event summaries. |
| `POST /api/events` | Explicit authenticated production action with a server-controlled actor. |
| `GET /api/history` | Legacy request and event history. |

For HTTP, a successful or identical replay is 200. Version or idempotency conflicts and disallowed business actions return 409; missing orders return 404; malformed fields return 400. Retry an uncertain network result with the same event ID. A rejected event replay remains rejected; a corrected request needs a new ID. A replay's returned order is the historical event snapshot, so fetch the order again for its current state.

```bash
python -m app.cli.lifecycle inspect ORD-045
python -m app.cli.lifecycle complete ORD-045 --workshop-id W6 --pieces 50 \
  --actor operator-a --reason "Workshop confirmed the first batch" \
  --expected-version 1 --event-id event-045-001
python -m demos.lifecycle_demo
```

The CLI supports inspect, complete, cancel, lapse, and reassign, with database and business-date options. Its actor flag is a local audit label. Use the current inspected version and workshop, not the illustrative values above.

Migration 002 upgrades older databases transactionally without reimporting CSV data. It reconstructs unconsumed reservation time from the old append-only queue history using the then-current workshop capacity. If historical queue or capacity values were edited outside the application, verify a backup before upgrading. The import initializes completed CSV orders with their full completed quantity; other orders start at zero.

Behavioral tests cover split and partial completion, cancellation and reassignment of remaining pieces, lapse, event replay and conflicts, concurrent version claims, FIFO decay, missing queue rows, rollback during reassignment or audit failure, database migration, HTTP, and CLI paths. The dynamic Agent tests also simulate a process exit after the lifecycle transaction to verify that retry does not repeat the event or queue update.
