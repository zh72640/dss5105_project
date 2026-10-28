# Week 8/9 progress and historical acceptance

Updated 2026-10-03 for MVP v0.3 on the original `ningtao` branch. This is a historical Sprint 1 record, not evidence that later dynamic-Agent work or the formal course presentation was completed.

The local course specification described a Week 9 Sprint 1 upload by 2026-10-16 15:00 and a 19:00 presentation with five minutes of talk and two minutes of questions. It called for problem and architecture, business value, early results, risks and assumptions, and a Sprint 2 route and success criteria. Detailed external daily plans existed for Weeks 4–6 only. The Week 8 feature scope below was an internal plan derived from the earlier handoff, not an instructor-approved list.

## Delivered at v0.3

- Migration 003 added durable `sessions` and `session_messages`, versions, and message sequence.
- The legacy session accepted a missing-order clarification, order answer, workshop-count or exclusion edits, exclusion clearing, objective change, preview, explicit confirmation, and closure.
- A draft did not touch production tables; confirmation locked and rechecked order, workshop, and queue facts before applying.
- Cross-session isolation of draft data, request replay and cross-endpoint key conflict, stale version, concurrent confirmation/edit, audit insertion failure rollback, order version checks, and remaining-piece allocation after partial completion were tested.
- UI, API, and CLI could create, restore, revise, replace, confirm, and close; browser refresh recovered the draft and proposal.
- v1/v2 database upgrades to v3 preserved production records and rolled back failed migration.
- The original production planner ran in single-workshop mode against the unchanged official simulator harness. Three baselines and four objectives across standard/shock scenarios with seed 5105 covered all 120 orders in 14 new runs.
- A written architecture, demonstration steps, risks, and route map existed. Formal slides, team identities, upload, and live rehearsal remained open.

An initial comparison recorded 396 unfavorable comparisons across scenarios and baselines, with ten distinct illustrative orders. The 396 entries were not 396 independent orders or system failures. Simulator order differences were affected by different queue histories and were not causal counterfactuals.

## Test and browser evidence

The recorded `evaluation/verify_mvp.py` run at 2026-10-03T02:39:34Z passed **168 tests** with no failures, errors, or skips. It included 13 new session core tests, one CLI, two HTTP, and two simulator checks over the earlier 150-test baseline. Offline parser results matched 60/60 and original behavior labels 30/30. Lifecycle and session demos each passed in temporary persistent databases; repeated confirmation did not assign twice. Official standard/shock baseline output stayed unchanged.

Chrome exercised missing order → ORD-045 → two-workshop limit → exclude W8 → refresh → confirm against a separate temporary database. The session ended `CLOSED` at version 5; the order became `WORKING` at version 1 with W5/150 pieces. After an interruption, documentation was completed from this saved run without repeating the full tests or calling a live model. See [verification summary](../evaluation/results/verification_summary.json), [test output](../evaluation/results/test_results.txt), and [session demo](../evaluation/results/session_demo.json).

For the standard scenario at seed 5105, the speed objective averaged 8.05 days and 1.67% late, compared with the random baseline's 21.52 days and 34.17% late. Its cost was 115,640 versus random 111,780 and minimum-cost baseline 85,960; its defect rate was 5% versus random 4.17%. Hybrid averaged 8.79 days and 3.33% defects. These were one-seed development-data results without independent holdout or multiple-seed statistical conclusions. The official simulator only supported single-workshop runs; split benefits were outside that comparison. Standard and shock scenarios consumed randomness differently, including rework samples.

The separate 2026-10-02 full live Gemini run remained `ACCEPTANCE_FAILED`: 14/60 matches and 46 final HTTP 429 cases. This Week 8/9 pass used offline and simulated SDK transport and did not change that outcome. Original Data Schema2 DDL, second human label review, independent holdout, explanation fidelity scoring, and business objective/policy approval still required external input. No Canvas upload or formal slides were claimed.
