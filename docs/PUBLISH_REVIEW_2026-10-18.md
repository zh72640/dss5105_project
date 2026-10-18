# Publication review — 2026-10-18

The user authorized another review followed by publication to `ningtao`, with English commit messages and files staged individually. The remote target was fetched before preparing the commits. `origin/ningtao` at `6e269de` is an ancestor of the reviewed application at `e12b801`; it is 24 existing commits behind, with no target-only commits. Publication preserves this history and uses a normal fast-forward push, without force.

The publication includes the reviewed hybrid planner, complete candidate plans, conditional alternatives, changed-approval explanations, Offline interpretation fixes, UI changes, evaluation tools, regression tests and review documentation. Related files are separated into commits for the allocator, alternatives, Chat, UI, evaluation tools, evidence and documentation. Each file is staged by its explicit path.

## Verification

- The fresh full Python regression passed **281 tests**. HTTP tests used temporary databases and loopback ports; model transports were mocked.
- The fresh frontend regression passed **47 tests**.
- The earlier Chromium acceptance, authenticated HTTP checks, 30-case Offline evaluation and 14-configuration simulator comparison remain recorded in the [scope review](SCOPE_FLOW_REVIEW_RESULTS_2026-10-17.md). They were not rerun merely to change their timestamps.
- Upstream CRLF endings were restored on seven touched files. Their normalized byte contents were checked unchanged, so this is formatting only. Historical simulator source hashes describe the bytes at the original measurement; the publication manifest records the final source bytes and LF-normalized hashes.
- Real model acceptance remains **NOT RUN**, as requested. AOCI full semantic-index authoring and the team's Primary Objective decision remain outstanding.

Fresh test logs and the source manifest are in [`evaluation/results/publish_review_20261018`](../evaluation/results/publish_review_20261018). The Python run emits ResourceWarnings about unclosed test database handles but has no test failures.

## Publication boundary

The incomplete local AOCI index and baseline, its raw Overview output, generated AGENTS integration, machine-specific host files, runtime databases, credentials, environments and caches are excluded. Published logs redact the local checkout path as `<REPO>`; the original local outputs remain available. The existing Q&A document and original workspace checkout are preserved.

The review intentionally retains calendar-day timing, the hard required-sole-workshop constraint, and the native LLM subgraph's single-workshop limit. It does not claim that `min_delay` minimizes global lateness, that Offline accuracy is live-model accuracy, or that local HTTP latency establishes an online response-time guarantee.
