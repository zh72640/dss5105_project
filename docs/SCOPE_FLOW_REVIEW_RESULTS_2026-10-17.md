# SweaterCo scope and flow review results

Verification ran on 2026-10-17; the initial handover was completed on 2026-10-18 after the interrupted session resumed. No real model acceptance calls were made, as requested. Changes were local and uncommitted at that handover. The subsequent user-authorized publication is described in the [publication review](PUBLISH_REVIEW_2026-10-18.md).

## Repository and branch selection

At the initial handover, the original workspace remained on `ningtao` at `6e269de`, with its existing Q&A document preserved. The independent clone is `remote-checkouts/dss5105_project-20261017`; review work began on `review/scope-flow-20261017`, based on `origin/yihua` at `e12b801`. Publication now targets `ningtao` from that reviewed code base.

Remote heads were checked again before the final handover work; they matched the initial inspection:

| Branch | Head | Treatment |
| --- | --- | --- |
| main | `5dfdca6` | Compared with the original workspace. |
| ningtao | `6e269de` | Original workspace; unchanged. |
| ningtao-fixed | `50a66d4` | Older history; its name does not make it the newest implementation. |
| tongling | `5b3e9cb` | Contains a clarification evaluator tied to the removed `app.agent.parser` API; not blindly merged. |
| xiaoyu | `87ca063` | Inspected remote head. |
| yatong | `e6cb8dd` | Inspected remote head. |
| yihua | `e12b801` | Latest application branch at inspection; selected for the review clone. |
| zhen | `bcf2047` | Scoring work already represented in the newer application history. |

All remote branches are available in the clone. No original production database was migrated, cleared or reused for verification. No commits or pushes were performed before the initial handover.

## Source-grounded architecture

The current application is FastAPI/Uvicorn with SQLite schema v9 and persistent, owner-scoped Chat v2 sessions. Startup builds a ModelRegistry from an environment snapshot. Offline mode interprets requests through rules; LLM mode uses the LangGraph runtime, dynamically loaded Markdown Skills and guarded native Tools. Tools delegate business decisions to services; the allocator computes plans, while repositories own SQL and transactions.

The business flow is request interpretation, evidence-backed requirement updates, database preflight, deterministic planning, saved recommendation, explicit confirmation, then production writes. SQLite holds authoritative business facts; workflow checkpoints do not replace them. Confirmation checks the owner, session/task version, recommendation ID, current facts and plan signature, with request replay protection.

Relevant entry points are `app/main.py`, `app/api/routes/chat.py`, `app/agent/runtime.py`, `app/services/chat/service.py`, `app/services/chat/operations.py`, `app/services/allocation/service.py`, `app/allocator/planner.py`, and `app/db/*`. The current native LLM allocation subgraph deliberately supports one workshop; the allocator and explicit Offline requests also support splits. Parser v1 and legacy session HTTP routes remain retired.

## Review findings and implementation

| Review item | Result |
| --- | --- |
| Approval changes after another order consumes capacity | Current upstream already blocked stale approval. Added explicit `REVIEW_CHANGED`, before/after differences, persisted conversation metadata, and the exact ORD-045 / ORD-096 regression with replay and renewed confirmation. |
| Weighted hybrid split does not optimize its own score | Fixed by enumerating integer completion breakpoints and minimizing weighted defect exposure at each feasible completion time. The review counterexample now allocates A20/B80, score 8.16. Small cases, including hard deadlines, match exhaustive enumeration. |
| No complete split candidates | Added up to five distinct complete `candidate_plans`, including quantities, completion, cost, quality, objective, warnings and constraints. The UI displays these even when single-workshop `candidate_ranking` is empty. |
| No actionable options after refusal/infeasibility | Added deterministic, explicitly conditional alternatives. Capability, workshop status and exclusions stay enforced. Options state whether the required sole workshop, deadline, objective or workshop limit must change. They never mutate the request or commit production. |
| Ambiguous preferred-workshop label | UI says “Required sole workshop”; the existing compatibility field remains a hard sole-workshop constraint. Soft preferences are still unsupported. |
| Language evaluation | Added a Chat v2 runner with isolated cases, full failure denominators, optional field labels and separate explanation review. Fixed word-boundary matching for BudgetWorks, a supported faster-split instruction and accidental allocation from sales-price queries. Gold labels were not changed. |
| Live smoke script could fail to use the registry or treat BLOCKED as success | Passed the registry and an explicit Gemini alias; a smoke pass requires an uncommitted recommendation. Selection and refusal handling were tested with mocks only. |
| Local latency and audit checks | Corrected the old export assertion: 20 previews plus 10 confirmations produce 10 business audit records. The script verifies the exact confirmation IDs and authenticated actor. |
| Legacy direct-allocation HTTP routes | Already removed upstream. They were not restored. |

The hybrid optimum is for the current order, fixed facts and the bounded set of allowed workshops. It is not a global schedule optimum over future arrivals. Candidate plans are the best plans from evaluated subsets, not every possible integer allocation. The original deadline-gated score in `app/allocator/scoring.py` remains separate from the planner's weighted objective.

## Verification evidence

Fresh evidence is saved under [`evaluation/results/scope_review_20261017`](../evaluation/results/scope_review_20261017). Earlier repository reports were not overwritten.

| Check | Observed result |
| --- | --- |
| Baseline before changes | 264 Python tests and 44 frontend tests passed. |
| Full Python regression after business changes | 280 tests passed. The log contains ResourceWarnings about unclosed test database handles; no assertion failures. |
| Final evaluation-helper regression | 4 tests passed after adding the provider-selection check; this includes one new test and three already counted above. No network/model calls. |
| Frontend regression | 47 tests passed. |
| Browser acceptance | Passed on a fresh headless Chromium profile: conditional alternatives, 390px mobile layout without horizontal overflow, complete split candidates, stale approval across two sessions, persisted differences after reload, renewed confirmation and disabled committed state. No page errors. Screenshots were inspected. |
| Authenticated local HTTP | 20 previews, 10 confirmations and exactly 10 matching audit exports passed. Preview P50/P95: 6.54/10.30 ms; confirmation P50/P95: 7.17/8.79 ms. These are offline local HTTP timings, not paint time, concurrent-load results or LLM latency. |
| Original 30 development requests through current Chat v2 | 30/30 service responses; 28/30 historical behavior labels matched; zero production rows written. R02 historical lookup and R13 sales-price query clarify or report scope boundaries, whereas the historical labels expect DECLINE. |
| Field accuracy / explanation faithfulness / independent holdout | Not measured: no field labels, independent explanation judgments or new holdout labels were supplied. |
| Simulator comparison | 14 configurations completed, matching the saved comparison metrics. Harness, seed data and adapter were unchanged; source hashes in the fresh report match the reviewed files. The official API evaluates single-workshop allocation, so it does not validate the split improvement. |
| Larger seeded hybrid example | A 2,000-piece order took approximately 43 ms with limit 2 and 386 ms with limit 8 in a single local measurement; not a load benchmark. |
| Real DeepSeek/Gemini acceptance | NOT RUN, explicitly deferred by the user. |
| Patch hygiene | `git diff --check` passed. |

The in-app browser plugin failed before connecting because its installed runtime module was missing. Browser acceptance therefore used a separate Playwright environment with the installed Chrome executable, a fresh browser profile and a disposable database. It did not read personal browser sessions or modify the project dependency lockfile.

## AOCI status

The installed CLI and MCP server both reported AOCI `0.1.0-rc20`. Initialization, source inventory, Guide/Scope checks, Rules and Overview were invoked. The initial scan inventoried 299 files. Overview delivered only the initialized skeleton, with **zero semantic entries**, `governance_aligned=false` and `model_full_cognition_reliable=false`.

This is not a completed semantic repository index or a successful full-cognition verification. The architecture and engineering conclusions above come from direct source review and execution evidence. Complete source-bound AOCI authoring remains outstanding; scans, generated scaffolding and test success must not be reported as completing it. AOCI scaffolding, raw status output, host configuration and generated AGENTS additions are retained locally and excluded from publication. Touched files originally using CRLF were restored to upstream line endings before publication; their normalized contents were verified unchanged. Published logs replace the machine-specific checkout path with `<REPO>`.

## Decisions that remain open

The supplied review still asks the team to choose its Primary Objective; no later Markdown decision was present in `Plans`. The implementation therefore retains the existing objective names: `min_delay` means earliest completion, not the global late-order fraction. The lateness objective, fairness/robustness policy, six-day workshop calendar and online latency acceptance target are not silently invented. Calendar-day queue decay, soft deadlines by default, and the hard required-sole-workshop behavior remain documented assumptions.

SQLite is the running source of truth; CSV files are initialization data. Full workshop/master-data editing, external synchronization, and independent model acceptance remain outside this completed code-fix and offline verification batch.

## Run and review

The independent local demo was restarted from the modified clone at <http://127.0.0.1:8017/chat>. It uses `runtime/scope-review-demo.sqlite3`, Offline mode and the local-demo actor.

From the clone root:

```bash
.venv/bin/python -m app.server --backend offline --db runtime/scope-review-demo.sqlite3 --port 8017 --no-auth
.venv/bin/python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/*.cjs
.venv/bin/python -m evaluation.evaluate_chat_language --mode offline --output-dir evaluation/live_results/chat-language
```

The first command is only needed if the existing demo server has stopped. The `--no-auth` mode is a local demonstration setting. Use the normal setup/authentication flow for an account-backed workspace.
