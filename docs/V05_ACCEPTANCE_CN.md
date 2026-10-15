# MVP v0.5 acceptance and evidence

Prepared 2026-10-09 from checks run on October 7–9. The release was `mvp_v0.5` on SQLite schema v4, with Parser/Prompt/legacy Session v1 and direct allocation Pipeline v0.2. The team inspected saved evidence after an interruption without resetting runtime data or repeating an approval. These are historical v0.5 results, not current live-Agent acceptance.

| Requested behavior | Implemented and checked at v0.5 |
| --- | --- |
| Local DeepSeek API integration | Server environment key, optional model/timeout, strict JSON validation, at most two attempts, explicit service errors, and key-free status. Mock HTTPS covered success, missing key, auth/balance/rate-limit failure, invalid response, redirect refusal, and no key in telemetry. No real account was called. |
| Clear allocation for a manager | Proposed and approved factual summaries of quantity, workshop, date, cost, and lateness; five recent approvals on Overview. Safari showed the committed summary after approval. |
| Actionable follow-up | DeepSeek parsed the current sentence while preserving older constraints; all modes had structured Edit details. Missing order, field conflict, ineligible workshop, infeasible plan, and service failure had distinct handling. Unsupported requirements remained blockers. |
| Text size | Small 14 px, Medium 16 px, and Large 20 px with relative component sizes and browser persistence. Controller tests checked storage and fallback; Safari checked reading and refresh. |
| Documentation and deployment | Changelog, secret setup, deployment/rollback, manual walkthrough, API contract, acceptance record, and frozen manifest, without migration or password reset. |

`evaluation/verify_mvp.py` passed **203 Python tests** with no failures, errors, or skips at 2026-10-07T21:03:45Z. Seven frontend controller tests passed. Offline parser cases matched 60/60; original behavior labels matched 30/30. Lifecycle, session persistence, replay, queue, and foreign-key checks passed. Fourteen official simulator strategy scenarios remained available without changing the allocation algorithm or course baseline. Evidence is in [verification summary](../evaluation/results/verification_summary.json), [Python test output](../evaluation/results/test_results.txt), and [frontend output](../evaluation/results/ui_controller_tests.txt).

## Safari check

The browser used an isolated database and localhost port 8015. It checked Overview, text sizes, New request, a missing-order question, form completion with ORD-045, recommendation, refresh persistence, and collapsed detail panels. On October 9, a saved draft was approved: 150 pieces went to BudgetWorks/W3, 120 cost units, ETA 2026-04-10, with lateness stated. The reply changed from Proposed to Approved and saved; the Overview showed the same decision, pending count fell from 34 to 33, active production rose from zero to one, and W3 listed ORD-045.

Browser control suffered window and timeout errors during the process. The final approval and Overview checks were eventually completed, but full Production, history detail/export, and phone-width browser flows were not. HTTP/controller tests should not be described as layout acceptance for those paths. `ui_latency.json` is a v0.4 measurement and was not rerun for v0.5.

On October 9, the local server health response reported `mvp_v0.5` with offline backend and existing login setup. No real DeepSeek or new Gemini request, public deployment, API key write, or user runtime reset occurred. A configured flag did not establish online connectivity. The old Gemini 429 failure record remained.

Natural-language summaries came from actual allocation fields. The model interpreted input; it did not invent numeric output or write the database. Budget caps, exact split ratios, master-data edits, and arbitrary expression support were outside the contract. Approval recomputed against current queue rather than treating a preview as final.

Use the [manual walkthrough](V05_TEST_WALKTHROUGH_CN.md), [DeepSeek setup](DEEPSEEK_SETUP_CN.md), [deployment guide](DEPLOYMENT_CN.md), and [v0.5 changelog](CHANGELOG_V05_CN.md) for that release. For current v0.6 dynamic chat use the [architecture guide](AGENT_SKILL_ARCHITECTURE.md).
