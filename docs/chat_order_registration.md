# Order registration in Requests

## File-level implementation plan

The existing Main Graph routes allocation and compatibility tasks. All sessions
currently carry an allocation task; manual registration exists only in Orders.
Registration needs its own durable business draft, not additional allocation rules.

1. Add `011_chat_order_registration.sql` and a registration repository for a
   session-scoped draft and request preparation ledger. Extend session snapshots
   with this separate task; retain the existing allocation state/schema.
2. Expose transaction-scoped entry points in the existing `order_intake` service
   so review/decision records and chat state/messages can commit atomically.
   Keep all comparison, lifecycle, verification and write rules in that service.
3. Add a registration schema, extraction prompt and Agent business node. The Main
   Graph routes `order_registration`; a fixed extraction/preparation step returns
   `TaskResult`. No new agent-callable Tool or Skill is needed for this fixed step.
4. `services/chat/order_registration.py` owns partial facts, field evidence,
   clarification, saved reviews and explicit decisions. Offline mode shares that
   service with a conservative rule extractor. No model result writes an order.
5. Add `order_decision` to Chat turns with the saved review ID and human verification
   payload. Requests renders a review card and reuses its persisted operation/retry
   client. New orders require confirmation; corrections require all changed fields,
   retyped ID and reason; rejection remains audited.
6. Test missing/matching/different orders, multiple turns, invalid/hallucinated
   extraction, approvals/rejections, session ownership, stale versions/reviews,
   retries, migration/restart and allocation compatibility. Use isolated databases.

## User flow

Start a Request with, for example:

> Add order ORD-901 for ABC: 300 knitted vests, TOPS, ordered 2026-11-11, due 2026-11-25.

The assistant collects missing fields conversationally, then displays the saved
comparison. Use the card to confirm creation, approve verified changes or keep the
registered values. A chat message such as “yes” does not bypass this confirmation.
The same registration audit is visible in Orders → Registration history.

Allocation remains a separate action after registration. The assistant supplies
the registered order ID for a subsequent allocation request. Active production
orders retain the existing correction protections.

## Verification — 2026-11-11

- Full Python regression: 490 tests passed, including 21 conversational registration
  tests covering atomic rollback, secondary verification, ownership, stale cards,
  idempotent retry, interrupted graph finalization, and migration from schema v10.
- Frontend regression: 87 Node tests passed using DOM stubs, including registration
  confirmation, safe rendering, decision timelines, session switches and lost-response
  recovery. These are automated client checks, not a visual browser inspection.
- Real DeepSeek (`deepseek-flash`) accepted the example above and a separate
  incomplete order followed by natural-language dates. Both reached a saved review;
  neither inserted an order before explicit confirmation. This online check used
  a disposable database and synthetic orders; other providers were not tested live.
- The existing local preview database was backed up before schema v11 migration.
  Its 120 orders were preserved. The updated server's health endpoint and OpenAPI
  contract expose the new `order_decision` action.

Run the deterministic checks from the repository root:

```bash
.venv/bin/python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/*.cjs
git diff --check
```
