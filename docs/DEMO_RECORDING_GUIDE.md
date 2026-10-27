# SweaterCo: a seven-capability demo

This 6–8 minute recording follows `Tech section/tech section.xlsx`, Sheet1,
cells A2:B8, supplied with the project. Use one ordinary allocation and one
allocation with special requirements. A short refused request demonstrates
that workshop restrictions are enforced.

## Before recording

1. Open the running local preview at <http://127.0.0.1:8000/chat> and sign in
   with the existing preview account. Login credentials stay outside this file.
2. Select **AI Agent** and the **deepseek** model, then click **＋ New**.
   The selection applies to new requests; an old offline request stays offline.
3. Check that the business date is **2026-04-01**. This is the sample data's
   planning date, separate from the computer's calendar date.
4. In **Orders**, verify that ORD-109 and ORD-041 are **Unassigned**. Return to
   **Requests**. ORD-045 and ORD-055 are already in production in this preview;
   do not use them for this recording.
5. Keep enough room for the conversation and **Review & decision** panel.
   Capture the four explanation sections and the recommendation card. Model
   wording and response times can vary; use the saved card as the numeric record.

The model reads `DEEPSEEK_API_KEY` from the server's startup environment.
No API key needs to be pasted into the UI. The existing preview uses a separate
database, `runtime/ui-preview-20261027.sqlite3`.

## Recording script

### 0:00–0:30 — Introduce the problem

Show the dashboard briefly, then open **Requests**.

Suggested narration:

> SweaterCo helps a dispatcher turn a natural-language request into a workshop
> allocation. It checks the registered order, compares eligible workshops,
> explains its recommendation, and waits for human confirmation.

### 0:30–1:15 — Detect missing information and ask for clarification

In the new DeepSeek request, send:

```text
Please allocate an order.
```

Expected: **Needs clarification**; the assistant asks which order to allocate.
The **Review required** panel identifies missing information. There is no
allocation recommendation to confirm.

Suggested narration:

> The request is incomplete. The assistant identifies the missing order
> reference and asks a clarification question before planning.

### 1:15–2:30 — Parse the answer and recommend an ordinary allocation

**Stay in the same request** and send:

```text
Allocate ORD-109.
```

Expected: the request resumes; the old missing-order issue clears. Registered
facts supply **Vest, 500 pieces, due 2026-04-13**. Point to **Requirements
checked**: order ID, remaining pieces, due date, objective, and workshop limit.

With no additional requirement, the configured default is **Earliest completion**
(`min_delay`) with one workshop. The model does not invent a customer preference.
The recommendation is a preview, marked **Awaiting confirmation**.

In the rehearsed snapshot, **GiantWeave (W5)** receives all **500 pieces**:
estimated delivery **2026-04-15**, cost **550.00** in the dataset's unspecified
currency, expected defect rate **6%**. The estimate is **two days late**. A late
estimate is a visible warning here because no hard on-time requirement was set.

Suggested narration:

> Providing the order ID is enough to recover the registered product, quantity,
> and due date. With no extra constraints, the system uses its default earliest
> completion objective. This is the earliest feasible recommendation, but it
> still predicts a two-day delay, which remains visible for review.

### 2:30–3:30 — Explain the plan, method, and tradeoff

Show the assistant's four ordered sections:

1. **Allocation plan** — workshop, quantity, delivery, cost, and quality estimate.
2. **Allocation method** — the selected objective and its scoring rule.
3. **Why this recommendation** — evidence and comparisons supporting the choice.
4. **Review before allocation** (sometimes shortened to **Review**) — warnings
   and the pending confirmation step.

Expand **Compare complete candidate plans**. For ORD-109, the rehearsed W5
completion score is **13.25 days** versus W3's **13.65 days**. W3 costs less
(400.00), so W5 is selected for the configured time objective, not lowest cost.
The explanation can also describe exclusions: W4 cannot make tops, W7 is
suspended, and W8's batch cap is too small.

Suggested narration:

> The explanation connects the recommendation to the chosen objective. W5 has
> the lowest completion-time score among eligible candidates. W3 is cheaper,
> so this recommendation involves a clear tradeoff. The figures come from the
> saved plan, and the dispatcher still decides whether to proceed.

### 3:30–4:00 — Confirm the ordinary allocation

Click **Confirm allocation** once on the recommendation card. Expected:
**Committed**, a confirmation message, and an updated **Decision timeline**.
The allocation is written only after this explicit action.

Suggested narration:

> I have reviewed the warning and will confirm this demonstration allocation.
> Confirmation records the assignment and updates the workshop workload.

### 4:00–5:45 — Allocate with special requirements

Click **＋ New**, keeping **AI Agent / deepseek**, then send:

```text
Allocate ORD-041 using weighted hybrid to one workshop. Exclude W6.
```

Expected registered facts: **Beanie, 600 pieces, due 2026-04-21**. The review
panel must show the weighted objective, **Workshop limit: 1**, and **Excluded:
W6**. The recommended workshop must not be W6, and the allocation must total
600 pieces. Show the method and explanation before clicking **Confirm allocation**.

In the rehearsed snapshot, **Little Loom (W4)** receives all **600 pieces**:
estimated delivery **2026-04-12** (nine days before the due date), estimated cost
**960.00**, and expected defect rate **2%**. Its weighted score is **0.20** versus
**0.80** for W2. W2 costs less (780.00), but its completion estimate is later.
These values assume the current queue snapshot and the preceding ORD-109 step;
changed workload can legitimately produce a different recommendation.

The new `weighted_hybrid` strategy imported from the zhen branch combines
**80% normalized signed lateness** and **20% normalized quality penalty**,
where quality penalty is `defect_rate × pieces / capacity`. Lower scores win
among eligible single-workshop plans. The weights describe the scoring formula;
they are not a claim of 80% faster delivery or 20% fewer defects.

Suggested narration:

> This request adds a specific allocation method and two constraints: use one
> workshop and exclude W6. The weighted method emphasizes delivery while also
> considering quality. The explanation identifies the selected method, shows
> the supporting comparison, and explains how the exclusion was respected.

### 5:45–6:30 — Show persistence and the audit record

Open **Orders**, search ORD-109 and ORD-041, and show **In production** and the
assigned workshops. Open **Workshops** to inspect the recorded workload, then
**Allocation history →** for the decisions. **Download decision logs** is
available on the Orders page if an exported audit artifact is useful.

Suggested narration:

> The confirmed assignments are now visible in Orders, and the decision history
> preserves the request and allocation record. In production means the software
> recorded an active assignment; this demo does not simulate manufacturing.

### Optional 6:30–7:15 — Reject an infeasible special requirement

Start another **＋ New** request and send:

```text
Allocate ORD-061 to W7 only.
```

Expected: **Needs clarification**, with a blocker explaining that W7 is
suspended and cannot accept the batch. There must be no valid allocation card
to confirm. The system may suggest alternatives for review; it must not
silently replace the required workshop or commit a different assignment.

Suggested narration:

> Special requirements also remain subject to workshop eligibility. W7 is
> suspended, so this request is blocked instead of being silently reassigned.

## Requirement coverage and acceptance

| Tech section capability | Recording evidence | Pass condition |
| --- | --- | --- |
| Parse Order Information | ORD-109 answer; ORD-041 special request | Registered order facts and stated constraints are visible and correct. |
| Detect Missing Information | First generic request | Missing order reference is reported; no plan is committed. |
| Ask Clarification Questions | Generic request, followed by ORD-109 in the same conversation | A question is asked and its answer clears the corresponding blocker. |
| Generate Workshop Recommendation | Both valid orders | A feasible, quantity-conserving recommendation is saved for review. |
| Explain Recommendation | Four sections and candidate comparison | Explanation states the actual method, evidence, tradeoffs, and limitations. |
| Allocate order with no additional requirement | ORD-109 | Default objective is visible; explicit confirmation commits the assignment. |
| Allocate order with special requirement | ORD-041 | Weighted strategy, one-workshop limit, and W6 exclusion survive confirmation. |

The workbook marked explanation and special requirements as **In progress**.
The demo exercises their current implemented behavior; it does not edit the
workbook or assert support for every possible constraint (for example, arbitrary
budget caps or an exact split are outside these cases).

## Rehearsal and repeating a take

Validated on **2026-10-27** using the real **DeepSeek / deepseek-flash** service.
The final service-level rehearsal passed missing-order clarification, continuation
with ORD-109, both recommendation/confirmation flows, and the suspended-W7
blocker. The final run needed no retries. Ordinary and special recommendations
took approximately **23** and **20 seconds**; leave this waiting time in the
recording plan. Earlier attempts included a retryable incomplete model response,
so the UI's existing retry action remains useful if a later take encounters it.

Rehearsal also exposed two input handling defects, now corrected: a resolved
missing-order ambiguity could survive the user's answer, and a model-supplied
single exclusion could remain a scalar rather than a workshop list. **107
targeted Python tests passed**, including continuation/replay, legacy issues,
unrelated blockers, special constraints, extraction, explanations, and prompt
loading. The UI steps above were checked against the current page controls;
this validation did not itself record or automate a browser video.

Live rehearsal uses a SQLite backup of the preview in a temporary directory.
Its confirmations do not allocate the orders in the preview used for recording.
The local rehearsal report is ignored by Git under
`evaluation/live_results/recording-demo-rehearsal.json`.

Actual recording confirmations do change the preview. **＋ New** starts a new
conversation; it does not reset an allocated order. For another complete take,
use a fresh copy of the preview baseline or choose fresh unassigned orders and
update the narration to their actual results. Do not delete business records
or reuse an already allocated order as if it were unassigned.

If model access fails, retry the same pending operation through the UI. Switching
to **Offline rules demo** requires a new request and should be labelled as an
offline demonstration, not a real DeepSeek run.
