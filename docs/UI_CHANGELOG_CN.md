# MVP v0.4 English Dispatch Desk changelog

Historical update: 2026-10-06, from commit `6b5244c` on branch `ningtao`. The course Word requirements and PowerPoint page sketches were turned into an English workbench. Original source copies remain in [requirements](requirements/README.md). The current v0.6 UI retains this workbench and adds Agent chat integration.

## Delivered workbench

| Page or feature | v0.4 behavior |
| --- | --- |
| Sign in | Local username/password login, logout, and eight-hour session. |
| Overview | Pending, clarification, allocation-today, and lapsed counts; inbox search and workshop queue view. |
| Request intake | New request dialog with natural language and default objective; sending saved a draft instead of production assignment. |
| Recommendations | Original message, registered order details, constraints, clarification, workshop candidates, plan, and ETA in one review path. |
| Decision review | Time components, cost, objective, eligibility reasons, Accept, and Reject & revise. |
| Allocation history | Order/request search, status filter, pagination, original and parsed text, approver/time, complete CSV/JSON export. |
| Workshop explorer | Name/ID, state, category, capacity, batch maximum, cost, defects, queue, and active orders. |
| Production | English completion, cancellation, reassignment, and lapse with reason and confirmation. |
| Narrow layout | Top navigation, single-column content, two-column statistics, and local table scrolling below 800 px. |

The legacy page remained at `/legacy` for compatibility. The normal `/` entry point used the new English UI. In the current release, legacy page visible strings have also been converted to English.

## Approval, retry, and identity

The v0.4 page called preview and explicit confirmation separately. A missing order, clarification blocker, closed session, or absent valid recommendation disabled Accept, and the service independently enforced the same checks. Confirmation rechecked order version and latest queue and atomically saved allocation, queue, messages, decision audit, and approver.

Reject & revise recorded a rejection turn and opened edits in the same legacy session. Closing the dialog did not reinstate the old recommendation or undo a committed allocation. Already assigned work required a Production action.

The browser stored an uncertain operation under its local account selection. “Retry safely” reused the request ID and expected version after network or 5xx uncertainty; rapid duplicate clicks did not make a second write. Drafts and messages remained in SQLite. Logging in again after expiry allowed the pending retry.

Migration 004 introduced accounts, hashed login tokens, and request actors. Passwords used salted PBKDF2-HMAC-SHA256 with 600,000 iterations; token hashes, not plain tokens, were stored. Cookies were HttpOnly and SameSite=Strict. HTTP approver identity came from login, and production HTTP ignored a client-supplied actor. Historical records without actor remained unattributed rather than receiving an invented name. The explicit local demo identity was not real-user approval.

At v0.4, all accounts shared a workspace and no department or tenant isolation existed. The service listened on localhost; those local HTTP cookie settings alone were not a public HTTPS deployment design. Later migration 007 added user/admin roles, and chat v2 added owner-scoped conversations, while underlying order data remains shared.

## Historical verification

At release, 181 Python tests and five frontend controller tests passed. Offline parsing matched 60/60, original behavior labels 30/30, lifecycle and session demos passed, and 14 simulator scenarios were retained. Sample authenticated local HTTP latency was under three seconds; see [latency data](../evaluation/results/ui_latency.json).

Safari checks covered login, overview, missing order clarification, ORD-045 follow-up, refresh recovery, candidates/explanation, and the rejection edit dialog. Browser control later failed, so final acceptance after revision, phone-sized layout, and full history/production click paths were not claimed as browser-tested. HTTP/controller tests covered some of those paths separately; see the [acceptance record](UI_ACCEPTANCE_CN.md).

No live Gemini call or public deployment occurred in that UI change. Browser and latency tests used separate temporary databases and did not rewrite original CSV, simulator baselines, or the user's runtime database. The functional commit was `5eff0da`; the release manifest is in `docs/release_manifest.json`.
