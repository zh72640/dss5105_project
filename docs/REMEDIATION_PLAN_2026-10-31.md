# Intake and validation remediation

Baseline: local `a6792ae`, synchronized with remote main `65ca124` before implementation. Existing uncommitted UI feedback changes are retained. This work addresses the reproducible defects from the October 31 review without changing the Agent–Skill–Tool–Service architecture or the explicit allocation confirmation requirement.

## File-level changes

1. `app/schemas/chat.py`, a new version of `allocation.extract`, and `app/agent/allocation_graph.py`: bounded incremental constraint operations, current constraint context, and explicit withdrawal of supported blockers. Existing prompt versions remain readable for request recovery.
2. `app/services/intake/` and `app/services/chat/{extraction,interpretation,constraint_patches}.py`: canonical dates and workshop identifiers; constrained objective spelling normalization; field and operation evidence checks; preserve existing exclusions; actionable extraction diagnostics. No business writes on partially valid extraction.
3. `app/services/chat/allocation_preparation.py`, recommendation contracts and UI: retain registered-fact differences and show them before confirmation. Preserve registered-order authority and do not add an order-master editing path.
4. Explanation service, prompt and tests: shorter evidence-grounded responses, validation of supported factual claims, and a deterministic fallback when generation cannot be trusted or is unavailable.
5. `run_clarification_eval.py`, labels and CI: replace retired parser imports with current APIs, separate extraction from end-to-end behavior, use temporary databases, and run reproducible offline checks without provider credentials.
6. Calendar experiment, setup/reset tooling, known limits and release notes: remove stale policy counts, provide a portable backed-up demo reset, repair the local environment, and document the current capability boundaries.

## Verification

Test schema and semantic rejection, additive/removal/undo sequences, registered differences, temporary failures and request replay, explanation fallback, UI recovery, and reset scope. Run the full Python and frontend suites, isolated browser acceptance, and a separately labeled real DeepSeek run. Preserve production/recording data and all audit/owner/version/confirmation safeguards.

## Delivery

Review and commit only source, tests, tooling and non-sensitive summaries. Do not commit runtime databases, credentials, backups, remote checkouts, or raw private traces. Synchronize the remote branch without force pushes and report the resulting commit and validation evidence. New order creation, multi-workshop AI planning, detailed scheduling and multi-tenant deployment remain explicit future capabilities.

## Completion

Implemented and verified; see [results and remaining limits](REMEDIATION_RESULTS_2026-10-31.md).
The imported gold labels were preserved with their policy/annotation discrepancies
documented, rather than changed to improve the evaluation score. Live observations
and mocked regression results are reported separately. The existing preview was
restarted with unchanged account and business-data counts.
