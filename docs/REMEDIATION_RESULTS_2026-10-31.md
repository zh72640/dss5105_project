# October 31 audit remediation

Work began on October 31 and publication was completed on November 1, 2026
(Singapore). The implementation starts from `65ca124`, including the upstream
`zhen` strategy and `tongling` clarification-evaluation changes. Existing local
message-feedback UI work and the calendar experiment were retained and verified.

## Changes

| Audit topic | Result and implementation |
| --- | --- |
| Incremental constraints | `allocation.extract` v4 exposes set/add/remove/unset/undo and current constraints. Ordinary exclusion instructions add to the existing list. Explicit list replacement, clearing, withdrawal and negation are checked. Clearing a required workshop keeps exclusions and the objective. |
| Short date evidence and wrong years | Month/day evidence can be a short quote when the full message identifies its field. Yearless dates use the session business year, including dates already past. Explicit years remain authoritative. Order dates cannot be inferred from a requested dispatch date. |
| Workshop names | Registered names normalize to IDs before validation while preserving the original quote. Context names come from the workshop repository, including custom imported names. |
| Unsupported evidence | Customer, product, category and exclusion polarity receive semantic checks. A quote containing only an order ID does not substantiate a customer or product. Negated clearing and undoing the wrong named constraint are rejected. |
| Objective typo | `minimun cost` and `mininum cost` resolve to the supported minimum-cost objective using bounded spelling rules. |
| Conflicting order facts | LLM preparation continues using registered facts. The supplied/registered differences persist through constraint-only revisions, appear in both review and recommendation cards, and enter the explanation payload. Confirmation still requires a current recommendation and explicit user action. |
| Failed extraction feedback | The response names the field needing restatement and reports a recognized order reference when present. It explicitly says the message has not changed the requirements. Partial extraction is deliberately not applied. |
| Pending replacement due date | A message saying a new due date will be confirmed later blocks preparation, even if a model omits that ambiguity. A grounded due-date reply clears the field-scoped blocker; register differences remain disclosed. |
| Order creation wording | The composer now asks for a registered order. Unknown-ID feedback explains the import workflow and that starting a chat does not create an order. |
| Explanation | `allocation.explain` v4 targets 110–170 words with plan/method/reason/review sections. Conservative checks reject unsupported IDs, dates, numbers and selected contradictions. Transient service failures, truncated/empty output and failed factual checks produce a visibly labeled verified summary; fallback reasons are audited. |
| Message feedback | Submitted messages remain visible while awaiting a response. Waiting dots, progressive reply rendering, reveal-now, reduced-motion support and reload/retry reconciliation are included. Progressive display is client-side animation after response receipt, not token streaming from the provider. |
| Environment | The expired temporary Python binding was repaired using the installed Python 3.14.3. `uv sync --locked --offline --python /opt/homebrew/bin/python3` resolved 68 packages and checked 66 installed packages. |
| Calendar test | The calendar experiment now derives its policy count; the test checks the complete policy/scenario set. Eight current policies × two calendars produce 16 runs. This is an experiment, not a change to production scheduling. |
| Evaluation and CI | The retired `app.agent.parser` import was removed. Current intent/extraction nodes and offline interpretation are used with temporary databases. Intake and extraction-only layers are labeled separately; extraction-only runs suppress routing accuracy/F1. CI installs locked dependencies and runs Python, frontend and offline intake checks on the active branches and PRs. |
| Reset and documentation | A portable `app.cli.reset_demo` requires an explicit database and stopped-server acknowledgement, backs up the complete database, preserves accounts/passwords and clears demo activity. The current architecture, setup guidance and known limits were updated. |

Old prompt versions remain available for pinned recovery. The Agent–Skill–Tool–Service–Repository
separation, owner checks, task/session versions, saved recommendation hashes,
transaction boundaries, request replay and production lifecycle remain in place.

## Verification

| Check | Observed result |
| --- | --- |
| Final full Python regression | **326 passed**, no failures/errors; temporary databases and loopback HTTP fixtures; model transports mocked. Existing SDK deprecation and test-resource warnings remain. |
| Frontend unit tests | **64 passed**. Includes registered-fact visibility and pending/typing/recovery behavior. |
| Real Chrome acceptance | **PASS**: delayed first response, message persistence, animated waiting, progressive text, reveal-now, reload, lost response, same-ID retry, 390px mobile and reduced motion. No page errors. Offline fixture; zero model calls. |
| Offline intake on original 30 messages | No parser errors; **28/30** historical labels matched; clarification precision/recall/F1 **0.875**. Differences: R02 historical lookup versus clarification, and disputed R16 date semantics. This is a rule baseline, not LLM accuracy. |
| Real DeepSeek extraction, final complete batch | **29/30 accepted**, one retryable `model_incomplete_output` on R15; zero evidence/format rejections in this batch. **R07, R12, R14, R17, R23 and R28 all accepted.** R01 and R05 also no longer exhibit the initial observed defects. |
| Separate R15 repeat | **1/1 accepted**. The original full-batch failure remains recorded. This does not turn the full-batch result into a first-pass 30/30 score. |
| Real DeepSeek workflow | **PASS**: required suspended W7 blocks; clear required workshop and select normalized 80/20; retain W6 exclusion; add BudgetWorks/W3; remove W3; explicitly confirm once. No working order before confirmation. |
| Reset regression | Existing activity remains in the backup; fresh activity is empty; account password hashes are preserved; no implicit target or missing-database creation. Tests use temporary files only. |

The last completed live workflow took 4.27 seconds for rejection, 19.97 seconds
for the first recommendation and about 33.5 seconds each for two revisions.
Those revisions each retried an explanation truncation using the same request ID.
That observation led to the final direct-summary fallback for truncated explanations;
the final regression explicitly checks fallback and replay without repeating the
saved plan. The observed live run had no factual-check fallbacks. These timings
are observations, not response-time guarantees.

The complete-batch extraction test intentionally sends even query messages directly
to the extraction node. It does not test routing, registered facts, feasibility,
confirmation, field-level accuracy or explanation quality. A valid extraction can
still correctly result in a blocked or out-of-scope workflow. The report does not
claim 100% semantic accuracy.

Machine-readable, non-sensitive results are in
[`evaluation/results/remediation_20261031/verification.json`](../evaluation/results/remediation_20261031/verification.json).
Detailed live outputs remain local under gitignored `evaluation/live_results/`:

- `remediation-final-20261031/`: complete final extraction batch.
- `remediation-r15-retry-20261031/`: separate repeat.
- `remediation-workflow-final-20261031.json`: live workflow and retries.

Earlier attempts are retained, including the initial workflow service failure and
the extraction run that exposed dispatch-date and pending-date issues.

## Reproduce

From the repository root:

```sh
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_*.cjs
uv run --locked python run_clarification_eval.py --backend offline --layer intake
```

With `DEEPSEEK_API_KEY` injected into the launching process, opt in to provider calls:

```sh
uv run --locked python run_clarification_eval.py --backend deepseek --layer extraction \
  --output-dir evaluation/live_results/new-extraction-run
uv run --locked python evaluation/verify_intake_live.py \
  --output evaluation/live_results/new-workflow-run.json
```

Use a new output path to preserve earlier evidence. See [demo reset and browser checks](DEMO_RESET.md).

## Remaining limits and next work

- Live models can still truncate extraction or fail transport calls. Chat retains
  request recovery; an extraction failure does not apply partial constraints or commit.
- Claim checking is deliberately conservative. A number occurring somewhere in
  evidence does not prove that every sentence associates it with the right entity.
  Independent human explanation evaluation is still needed.
- The imported labels need independent annotation review, especially R16 and R14's
  old soft-preference note. Labels were not altered to improve scores. A holdout
  15-complete / 10-ambiguous / 5-query set and no-clarification/template comparisons
  remain evaluation work; the original 30 are development cases.
- LLM basic allocation supports one workshop; explicit split planning remains in
  Offline mode. `preferred_workshop` is a hard constraint. Budgets, exact splits and
  soft preferences are unsupported and must be clarified or withdrawn.
- New chat requests use existing registered orders. Order creation/editing UI,
  multi-tenant deployment, full production calendars and global scheduling are future
  features, not fixes silently introduced by this publication.
- Business dates remain fixed per session. The demo seed uses April 1, 2026; the
  real calendar date does not silently replace that simulation date.

The current demo database and credentials were preserved. Runtime databases,
backups, credentials, private model traces and local branch checkouts are excluded
from publication. Publication targets the existing `ningtao` branch without force.
