# MVP v0.3 changelog and commit record

Historical date: 2026-10-03. Work began at `df50f64` on the original `ningtao` branch. Commits were divided by feature:

| Commit | Change |
| --- | --- |
| `60e032f` | Persistent clarification sessions with atomic allocation confirmation, migration 003, state and migration tests. |
| `bdb179e` | Resumable session drafts in UI, API, and CLI, including refresh/retry and a continuous demo. |
| `d6062b5` | Production allocation objectives compared with unchanged official simulator baselines. |
| `c471780` | Reliability tests and MVP v0.3 acceptance evidence. |
| `5a1267b` | Deployment, architecture, session, and database documentation. |

Later Week 8/9 materials and the release manifest were handled in separate documentation commits. File paths below describe their historical location; some are now in service/tool packages.

Migration 003 created `sessions` and `session_messages` without changing 001 or 002, and upgraded older databases transactionally. The legacy session service added bounded reply syntax, draft preview, version checks, explicit confirm/close, shared idempotency, and atomic writes. HTTP, page, CLI, and demonstration paths could recover a saved draft and response. A browser check exposed a refresh bug that restored the draft but lost the preview and guidance; that was fixed.

Initial or full-replacement messages used frozen Parser v1, while short follow-ups were fully matched to supported commands. Unknown trailing constraints were not silently swallowed. Replacement cleared omitted earlier constraints with a UI warning. Sending or revising only previewed; confirmation rechecked current queue and rejected a changed order version, then saved messages, draft, request/decision audit, allocation, and queue in one transaction.

The application release version advanced to v0.3, while the direct allocation pipeline stayed v0.2 so existing allocation keys could replay. The simulator adapter called the production planner in single-workshop mode because the official harness could represent only one workshop. The planner's objective or hybrid weights were not tuned to the comparison.

The saved run passed **168 tests** with no failures/errors/skips, 60/60 offline parser cases, and 30/30 original behavior labels. Session and lifecycle demos used persistent temporary databases. Chrome verified missing order, edits, refresh, confirmation, and one allocation. Fourteen simulator scenarios at seed 5105 produced 24 new-policy/baseline comparisons. Speed objective averaged 8.05 days and 1.67% late in standard conditions, while cost and some quality measures favored baselines. The report retained 396 unfavorable comparison entries and ten distinct order examples. See [historical acceptance](WEEK8_WEEK9_ACCEPTANCE_CN.md).

Original data, official harness, Week 4 baseline, Parser/Prompt v1, migrations 001–002, and user runtime database were preserved. No credential, environment file, virtual environment, database, or raw provider error was committed. The live Gemini full-run result remained failed; missing Schema2, independent labels/holdout, explanation review, and business-policy confirmation were open. Formal Week 9 slides, upload, and rehearsal were not claimed as done.
