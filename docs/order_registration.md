# Manual order registration

## Design and file plan

The existing register reads seeded orders and the production service changes their
lifecycle. It has no manual registration or audited correction workflow. Manual
registration is a deterministic operation: API → Service → Repository. It does not
require a new Agent, Tool or Skill, and allocation confirmation remains in Chat.

1. `app/schemas/order_intake.py` defines validated order facts and explicit review
   and decision contracts. `app/db/migrations/010_order_intake.sql` adds durable
   review/decision records; `database.py` upgrades existing databases transactionally.
2. `app/db/order_intake_repository.py` owns SQL. `app/services/order_intake.py`
   owns comparison, authorization, secondary verification, concurrency and replay.
3. `app/api/routes/order_intake.py` exposes authenticated review, decision, recovery
   and history endpoints. `app/ui/order-intake.js` and the Orders page provide the
   entry form, field comparison, explicit decision and audit viewer.
4. Verify isolated SQLite creation/upgrade, matching and conflicting orders,
   approval/rejection, races, replay, ownership and production protections; then
   run regression and browser checks. Never use the runtime database as a fixture.

## Behavior

- Enter the order ID, customer, product, category, pieces, order date and due date.
  IDs use the existing `ORD-001` / `O1` formats. IDs/categories are uppercase;
  surrounding whitespace is trimmed. Text case differences remain visible.
- Checking saves both the submitted input and normalized facts. Lookup is by exact
  normalized order ID. No customer/product guessing or automatic order creation.
- A missing order requires **Confirm new order**. An identical order is recorded
  as a match without creating a duplicate or changing its version.
- A differing order shows every changed field. Approval requires checking every
  difference, retyping the order ID and giving a reason. Rejection also requires a
  reason and records the proposed values without changing the order.
- Corrections are limited to READY/UNASSIGNED orders with no completed pieces or
  active allocations. Production events continue to use the existing lifecycle
  service. A denied approval is recorded, including the reason it was blocked.
- A transaction re-reads the full reviewed snapshot and version before creating
  or updating. Changes made since review require a fresh review. An update bumps
  the order version, so existing allocation previews cannot silently confirm old
  facts. Rejection can still be recorded after the order has changed.
- Each review has one final decision. Stable request IDs replay the recorded result;
  changing a payload under the same ID is rejected. Reviews and decisions record
  the authenticated actor, UTC time, before/proposed/after facts, field differences,
  verification, reason and outcome. A blocked decision also closes that review.
- Audit history includes pending, matching, approved, rejected and blocked reviews,
  including decisions about orders that were never created. All authenticated
  workspace users can read history; only the review owner can decide or resume it.

## HTTP endpoints

- `POST /api/order-intake/reviews`: save and return a comparison; no order mutation.
- `GET /api/order-intake/reviews/{review_id}`: resume the owner's saved review.
- `POST /api/order-intake/reviews/{review_id}/decision`: explicitly create, update
  or reject using a request ID, expected version, reason and verification evidence.
- `GET /api/order-intake/history?order_id=ORD-045&limit=50&offset=0`: paged audit
  history; omit the order ID to include all reviews.

Schema version 10 is additive. Existing order, allocation and audit rows are
preserved. Back up a deployed database before starting the upgraded application;
the normal database initializer applies the migration atomically.

## Integration and verification — 2026-11-11

Fetched all origin branches before implementation. `origin/main` at `8470685`
already contained all other branch tips: ningtao, ningtao-fixed, tongling, xiaoyu,
yatong, yihua and zhen. Fast-forwarded the working ningtao branch from `e5b56a5`
to that main commit. The two pre-existing local dashboard chart edits were kept
separate from this feature.

- Full Python regression: 469 tests passed, including 19 registration service,
  authenticated HTTP and migration tests. Test databases are temporary; models are
  offline or mocked. No live provider calls or runtime database changes.
- Frontend controller suites: 78 tests passed (68 existing and 10 registration
  tests). Registration tests cover explicit decisions, secondary verification,
  rejection, lost responses, reload/retry, recorded conflicts, input validation,
  corrupt recovery data and account separation.
- Browser layout/interaction acceptance was not completed: the browser access host
  was unavailable, and the native Chrome session was in active use. Controller tests
  use a DOM stub and do not establish visual layout quality.

Reproduce the automated checks from the repository root:

```bash
uv run --no-sync python -X utf8 -m unittest tests.test_order_intake -q
uv run --no-sync python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/*.cjs
git diff --check
```
