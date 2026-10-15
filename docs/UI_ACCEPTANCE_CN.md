# MVP v0.4 UI requirements and acceptance

This is a historical v0.4 record from 2026-10-06. The source documents were `Track2_UI_Requirements.docx` and `UX design.pptx`; unchanged repository copies are linked in [requirements](requirements/README.md). The user selected English for the page. Use the [current UI guide](UI_GUIDE_CN.md) for today's interface.

| Source requirement | Delivered v0.4 behavior | Evidence |
| --- | --- | --- |
| FR-01 Request Intake | New request with natural-language input, default objective, and durable draft. | HTTP and browser missing-order request. |
| FR-02 Clarification Handling | Block incomplete requests; answer with order ID, revise one field, or replace draft. | HTTP clarification/rejection/revision/confirmation and Safari refresh. |
| FR-03 Workshop Eligibility | Status, category, exclusions, batch maximum, and visible refusal reason. | Allocator tests and UI display; suspended W7 never assigned. |
| FR-04 Delivery Estimate | Queue + processing + pickup; multi-workshop completion uses the latest part and whole-day display. | Allocator/delivery tests and Safari candidate ETA. |
| FR-05 Recommendation | Delay, cost, defects, and weighted hybrid objectives. | Planner and 14 simulator scenarios, objective selector. |
| FR-06 Explainable Allocation | Part quantities, time components, cost, reason codes, exclusions. | Safari ORD-045/FreshStart explanation and saved audit values. |
| FR-07 Decision Audit | Full filtered/paged history, original/parsed text, approver/time, CSV/JSON export. | 33-record pagination/export, rollback, actor spoofing refusal. |
| FR-08 Workshop Explorer | Filter by workshop identity, status, and category; inspect capacity, batch, queue, assignments. | Active Accessories, Suspended, and name-query tests without mutation. |

The sketches mapped to Sign in, Overview, Recommendations, Decision review, and Allocation history. Workshop explorer and Production were explicit additional entries. Accept returned to Recommendations; Reject saved a turn before opening revision in the same session. An empty inbox displayed “All orders are assigned.”

## Automated and browser checks

The saved 2026-10-05 regression passed **181 Python tests**, including 13 new desk tests, with no failures/errors/skips. Offline parser matched 60/60; original behavior labels matched 30/30. Lifecycle, session, replay, queue, and simulator baselines continued to pass; 14 strategy scenarios ran. Five Node controller tests added on October 6 covered confirmation conditions, persisted retry, first-turn retry, version conflict, and rapid duplicate confirmation. They used a minimal DOM stub, not full browser layout.

The local offline authenticated HTTP performance sample used a temporary database with 120 imported orders and eight workshops. All samples were below three seconds: preview p95 4.65 ms and max 6.82 ms across 20 calls; confirmation max 3.99 ms across ten; one login sample 72.81 ms. These are not browser rendering, concurrent load, or live model latency guarantees. See [latency data](../evaluation/results/ui_latency.json).

Safari on a separate localhost port and temporary database checked login, 34 initial inbox items, real workshop queues, a missing-order request with Accept disabled, refresh recovery, ORD-045 follow-up, a FreshStart proposal for 150 pieces and 150 cost units with ETA 2026-04-05, an explanation of 0 + 1.5 + 2 = 3.5 days, and Reject & revise. A cramped parsed-field grid was corrected and route navigation/focus improved. Later browser control failed with window enumeration timeouts. The complete revision-to-approval-to-export click path, mobile layout, and Production browser flow were not claimed as passed; HTTP tests covered parts separately.

Requirement boundaries at that release included no independent user timing study, no tamper-proof external audit store, no phone-device acceptance, no second reviewer of labels, no independent holdout, and no separate explanation fidelity score. The full live Gemini acceptance still failed due to rate limits. The original Schema2 document was not available.

Current code has since added roles, chat v2, dynamic Skills, and additional tests. Do not use this v0.4 record to infer current live-provider quality.
