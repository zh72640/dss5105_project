# Scope and flow review implementation

## Baseline and working copy

The independent clone is based on `origin/yihua` at `e12b801`, on local branch
`review/scope-flow-20261017`. The original Workspace and its database remain intact.
This review applies the user's 2026-10-16 scope/flow review to the new Chat v2
architecture, rather than restoring retired Parser v1 or session APIs.

Remote branch findings relative to the original `ningtao` at `6e269de`:

| Branch | New commits relative to ningtao | Finding |
| --- | ---: | --- |
| main | 17 | Includes the previous dispatch implementation, scoring functions and custom CSV import. |
| yihua | 24 | Latest application development: FastAPI, LangGraph, native tools, Chat v2, model registry, roles, DB v9 and frontend recovery. |
| tongling | 20 | Adds clarification labels, evaluation script and CI; its script imports the retired `app.agent.parser`. |
| ningtao-fixed | 9, with 6 ningtao-only commits | Historical October 3 integration branch, not a newer fix release. |
| zhen | Diverged | Scoring work is already incorporated into main and yihua. |
| xiaoyu / yatong | Older | No new application changes to adopt. |

The unmodified yihua checkout passes 264 Python tests and 44 frontend tests.
HTTP tests require permission to bind loopback ports in the execution sandbox.
Tests use temporary databases and scripted model transports, not live providers.

## Current review findings

- Chat v2 already compares recommendation, task and facts hashes in a transaction.
  A changed plan returns a new uncommitted recommendation. Add the exact two-order
  review reproduction and explicit change details rather than reimplementing approval.
- The weighted hybrid split counterexample remains valid. Fix its own objective,
  preserving the four configured objective names and unchanged official harness.
- Full split candidates and deterministic refusal alternatives are missing.
- `preferred_workshop` remains a required sole workshop. Preserve this hard constraint
  and make its meaning explicit in the interface; alternatives require authorization.
- The current LLM allocation subgraph intentionally accepts a single workshop.
  Preserve that product boundary; allocator/offline split support is evaluated separately.
- The legacy direct-allocation HTTP endpoints have already been retired. Do not restore them.
- Primary course objective, operational calendars and final latency targets still need
  a team decision. The user asked to refer to later Markdown; no objective is invented here.

## File-level implementation sequence

1. `app/services/chat/service.py`, `tests/test_chat.py`: explicit `REVIEW_CHANGED`
   response and auditable old/new plan differences; concurrent-order regression,
   renewed approval and idempotent replay.
2. `app/allocator/planner.py`, `tests/test_allocator.py`: exact weighted hybrid
   integer planning for bounded workshop subsets; top-K complete candidate plans;
   exhaustive small-instance and review-counterexample verification.
3. `app/services/allocation/alternatives.py`, `preflight.py`, `service.py`:
   deterministic proposals to release a required workshop, relax a hard deadline,
   or increase the permitted workshop count. No draft mutation or production writes.
   Preserve category, status, exclusions and all constraints not explicitly listed.
4. `app/offline/reply.py`, `app/ui/chat-common.js`, `app/ui/chat.js`, relevant tests:
   show complete candidate plans and proposal tradeoffs; distinguish required sole
   workshop, unchanged constraints and explicit re-review.
5. Documentation and fresh verification: update the current behavior and known
   limitations, record branch findings, run focused regressions then the full suite,
   simulator comparison and local HTTP/browser smoke checks on an isolated database.

## AOCI and evaluation boundaries

The language check exposed three reproducible intake boundaries. Extend the file-level
work to `app/services/chat/interpretation.py` and `app/offline/interpreter.py`:
prevent sales quote queries from becoming allocations, match the word "budget"
without matching BudgetWorks, and distinguish supported faster-split instructions
from hypothetical questions. Add behavioral regressions without changing gold labels.

AOCI 0.1.0-rc20 was initialized in this clone and scanned 299 baseline files.
The scan is a source inventory, not a completed semantic cognition index. Formal
coverage and final status must be reported from AOCI's actual outputs.

No existing business database is migrated or reused for testing. Provider credentials
are never printed. Live evaluation can run only when an appropriately configured
provider is available; offline/mocked success must not be described as live success.
