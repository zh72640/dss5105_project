# Dispatch Desk and Conversation Assistant guide

This page retains its historical filename for existing links. The current English UI is served at `/` for the desk and `/chat` for the conversation assistant. Complete [setup and account creation](UV_SETUP.md), start the local server, and open <http://127.0.0.1:8000>. Both entry points use the same authenticated business database.

## Sign in and choose a mode

Sign in with a local account. The desk has Overview, Recommendations, Allocation history, Workshop explorer, Production, and Conversation assistant sections. Text size controls persist across refresh. The conversation page offers **Offline rules demo** and **AI Agent** modes. AI Agent requires a configured model with native tool calls. Offline rules are a separate demonstration and do not prove that the dynamic Agent ran.

The business date determines queue aging and estimated completion; audit timestamps are actual UTC time. A model being listed as configured does not prove live provider access or quality.

## Ask or recommend in the conversation

Select **New request** and enter a question or allocation request, for example:

```text
Allocate ORD-045 at the lowest cost, using at most two workshops, excluding W3.
```

The Agent selects a Skill, loads its instructions, and calls permitted tools to query records, check requirements, compare workshops, or calculate a plan. If required information is missing or conflicts with the order register, it asks a specific question. Respond in the same session so the saved context and pending question are available. A new requirement can invalidate an earlier recommendation and require a new calculation.

An order or workshop answer is based on registered data returned by tools. A recommendation card is a preview and does not change a production allocation or workshop queue. The saved card identifies the recommendation and task version. Use **Open recommendations** to review it in the desk if desired.

## Review and confirm

Read the proposed workshops, split quantities, estimated date, cost, eligibility checks, and warnings. The desk's **Why this plan?** and **Calculation & eligibility details** surfaces give the supporting facts. Single-workshop scores are comparisons; a multi-workshop recommendation comes from the checked integer planner.

Use the **Confirm** control on the specific conversation recommendation card, or **Accept allocation** on the matching desk card. The server verifies account ownership, the recommendation ID, session and task versions, current order and queue facts, and the recomputed plan before committing in one transaction. Confirmation cannot be given by merely typing “confirm” into a message. If you say “confirm, but change the quantity to 500,” the change is handled first, the old card is superseded, and a new confirmation is required. A stale card cannot be accepted.

If the network response is uncertain, use the displayed retry control and keep the original request ID. Repeated confirmation of the same saved operation does not add a second allocation or queue reservation.

## Use the desk's other sections

- **Overview:** Review pending orders, open requests, recent approvals, the business date, and workshop queues. Recent approvals are historical decisions; use Production for current progress.
- **Recommendations:** Select a request, use **Edit details** to change supported constraints without AI, inspect a saved preview, reject and revise, or accept a valid card.
- **Allocation history:** Filter recorded decisions, open their audit details, or export all records as CSV or JSON. Export includes records outside the current page and filter.
- **Workshop explorer:** View status, category capability, capacity, batch limit, queue, cost, defect rate, and active named orders. Imported anonymous workload can contribute to a queue even when no named order is shown.
- **Production:** Load the current order, enter an audit reason, review the current version, and record completion, cancellation, lapse, or reassignment. A completion quantity is incremental, not cumulative. Reassignment preserves the previous allocation if the new plan is infeasible. If the order version changes, reload it before deciding.

## Review the Agent trace

An authenticated session owner can request `GET /api/chat/sessions/{session_id}/trace`. It lists loaded Skill names and hashes, tool names, arguments and results, task state before and after, and pause or resume events. This trace is the reviewable evidence of what the Agent actually executed; hidden model reasoning is not part of the audit.

For business rules and recovery behavior, see [Dynamic Agent, Skills, tools, and business state](AGENT_SKILL_ARCHITECTURE.md). For live-model and deployment limits, see [Known limits](../KNOWN_ISSUES.md).
