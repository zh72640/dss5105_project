# Order registration

Register an order through **Orders → Add order** or directly in **Requests**. Both entry points use the same comparison, verification, transaction, and audit rules. Registration and allocation are separate decisions.

## Conversational entry

Start a Request with a complete sentence, for example:

> Add order ORD-901 for ABC: 300 knitted vests, TOPS, ordered 2026-11-11, due 2026-11-25.

The assistant extracts the supplied fields and asks for anything missing. Reply in the same conversation to complete or revise the saved draft. LLM mode understands contextual answers; Offline mode accepts explicit field labels and complete dates. Dates require an explicit year.

Once all required facts are available, inspect the saved review card. A message such as `yes` does not bypass the explicit confirmation controls. Revised or ambiguous details withdraw the previous review so its old card cannot be approved. Cancelling a reviewed registration or archiving its Request records the rejection.

After confirmation, send `Allocate ORD-901.` to request an allocation preview. Creating an order does not reserve workshop capacity.

## Manual entry and review rules

1. Enter order ID, customer, product, category, pieces, order date, and due date. IDs use `ORD-001` or `O1` formats. Categories are `TOPS` or `ACCESSORIES`; pieces must be a positive whole number. Due date cannot precede order date.
2. Select **Check order**. The service normalizes IDs/categories and surrounding whitespace, then looks up the exact order ID. Customer/product names do not select an order implicitly. Both submitted and normalized facts are saved.
3. If missing, choose **Confirm new order** or **Do not add order**, with a reason. No order is created by checking.
4. If every field matches, the service records the match without a duplicate or version change.
5. If fields differ, inspect every difference. Approval requires checking all changed fields, retyping the exact order ID, and giving a reason. **Keep registered values** records rejection with the proposed values and reason.

Corrections are limited to READY/UNASSIGNED orders with no completed pieces or active allocations. Production actions use the lifecycle service. Denied approvals are recorded with the blocker.

Each decision transaction rereads the full reviewed snapshot and version. Changed facts require a fresh review. Updates increment the order version, invalidating allocation previews based on old data. Rejection can still be recorded after the order changes.

Each review has one final decision. Stable request IDs replay that result; changed payloads under the same ID conflict. Blocked decisions also close the review. Browser recovery retains uncertain operations for retry without duplicating a write.

## Audit and access

**Registration history** includes pending, matching, approved, rejected, and blocked reviews, even for orders that were never created. Records include actor, UTC time, submitted/proposed/registered facts, differences, verification evidence, reason, outcome, and before/after snapshots.

Authenticated workspace users can read the shared history. Only the review owner can decide or resume it. Chat decisions also require the current session version and review ID.

## Implementation and HTTP contracts

`app/schemas/order_intake.py` and `order_registration.py` define input contracts. `app/services/order_intake.py` owns comparison and writes. `app/services/chat/order_registration.py` owns conversational drafts and decisions; `app/agent/order_registration.py` performs fixed model extraction. Repositories own SQL. The manual form and chat card live in `app/ui/order-intake.js` and `chat-registration.js`.

| Endpoint | Operation |
| --- | --- |
| `POST /api/order-intake/reviews` | Save a comparison without changing an order. |
| `GET /api/order-intake/reviews/{review_id}` | Resume the owner's saved review. |
| `POST /api/order-intake/reviews/{review_id}/decision` | Explicit create/update/reject with request ID, version, reason, and verification. |
| `GET /api/order-intake/history` | Paged history; optional `order_id`, `limit`, and `offset`. |
| `POST /api/chat/sessions/{session_id}/turns` | Messages collect details; `action=order_decision` submits a saved review decision. |

Migrations 010 and 011 add review/decision audit and conversational draft/replay tables without replacing existing business data. Follow the [backup and upgrade guide](deployment.md) before upgrading a deployed database.

## Verification

Registration tests use isolated databases and scripted model responses. They cover creation, identical and different orders, approval/rejection, production blockers, ownership, migration, rollback, stale reviews, and retry/recovery. Client tests use DOM stubs and do not establish visual layout quality.

A separate November 11, 2026 check with real DeepSeek (`deepseek-flash`) verified one-sentence extraction and a missing-date follow-up using synthetic orders in a disposable database. Both reached review without inserting an order before confirmation. This is a limited provider observation, not a reliability guarantee.

```bash
uv run --no-sync python -X utf8 -m unittest tests.test_order_intake tests.test_chat_order_registration -q
node --test tests/test_order_intake_ui.cjs tests/test_chat_registration_ui.cjs tests/test_chat_ui.cjs
```
