# Strategy and explanation integration

## Scope and source review

The reviewed remote branches are `main`, `ningtao-fixed`, `tongling`, `xiaoyu`,
`yatong`, `yihua`, and `zhen`. Relative to this workspace, `zhen` commit `0ffc0b8`
adds normalized weighted scoring and an isolated queue-insertion simulation.
`tongling` adds clarification evaluation files; these do not change allocation.
The other branches have no new non-merge implementation commits for this task.

## File-level integration plan

1. Add `weighted_hybrid` in `app/allocator/` and the existing objective schemas,
   intake parser, CLI, Tool schema and UI labels. Preserve the existing `hybrid`
   objective. Match zhen's single-workshop formula: 80% min-max-normalized signed
   lateness plus 20% min-max-normalized `defect_rate * pieces / capacity`.
   Constant ranges contribute zero. This method supports one workshop; explicit
   split requests must produce a clear blocker instead of a different algorithm.
2. Preserve the branch's `harness/simulate_new.py` and `harness/insert_production_queue.py`
   unchanged as standalone evaluation scripts, alongside the official `simulate.py`.
   Current production storage records aggregate workload rather than a complete
   ordered schedule. Integrating queue reordering into live commits would require
   a separate scheduling model and concurrency/revalidation design.
3. Extend the saved recommendation projection in `app/services/allocation/contracts.py`
   and `app/schemas/allocation.py` with optional, typed explanation evidence.
   Populate evidence from the already verified saved result, never live mutable
   workshop data. Old recommendations remain readable without new evidence.
4. Add a versioned `allocation.explain` prompt under `app/prompts/catalog/` based
   on the supplied `Explaination Template/Track2_Reasoning_Explanation_Templates(in).csv`.
   Present the plan, method, evidence-based rationale, limitations and explicit
   review step in that order. Adapt the template's fixed minimum-lateness wording
   to the actual selected objective. Never claim approval before confirmation.
5. Reuse `DEEPSEEK_API_KEY` through the existing immutable startup configuration.
   Add an opt-in smoke/workflow check using an isolated temporary database.
   Verify objective mathematics, parser grounding, explanation provenance,
   unchanged approval/replay/staleness guards and the real DeepSeek workflow.

No API credentials, local preview accounts, runtime databases or unrelated
work-calendar experiment files belong in this change.

## Implemented behavior

- `weighted_hybrid` is an additional objective; `min_delay`, `min_cost`,
  `min_defects` and the existing 60/40 `hybrid` keep their original formulas.
  Eligibility, user exclusions, batch caps, required sole-workshop constraints
  and hard deadlines are enforced before the normalized comparison. Stable
  score ties follow the existing time/cost/workshop-ID ordering. The source
  simulator used insertion order for exact ties.
- A requested multi-workshop weighted plan is explicitly blocked. The zhen
  policy has no split formulation; an unrequested approximation is not used.
- Recommendation snapshots now retain the method, formula, candidate scores,
  queue/production/pickup estimates and exclusion reasons. The explanation node
  reads this snapshot after the guarded plan has been saved. Its output never
  changes the allocation. Legacy records without evidence still load; changed
  facts invalidate stale explanations and require renewed review.
- The explanation uses four sections: **Allocation plan**, **Allocation method**,
  **Why this recommendation**, and **Review before allocation**. The English
  columns of all 48 supplied templates are preserved in
  [the source template extract](requirements/Track2_Reasoning_Explanation_Templates.csv).
  The original fourth column contained question marks and was not used. Source
  sentences that hard-code minimum lateness or claim approval are conditional,
  not universal instructions. The active prompt is `allocation.explain` v3.
- Real testing found an existing reply guard treating “No allocation has been
  committed” as a success claim and replacing the whole explanation. The guard
  now distinguishes explicit negative claims while still rejecting a later
  unsupported affirmative claim in the same reply.

## Verification on 2026-10-27

- **305 Python tests passed**, covering all tracked Python test modules and
  the new strategy tests. Existing unrelated untracked experiments were excluded.
  Coverage includes authentication, extraction grounding, Tool ordering,
  eligibility, transactions, stale facts, replay, production events and legacy
  explanation records.
- **56 frontend tests passed.**
- The new policy matched `zhen/0ffc0b8` on **360 order/queue combinations**
  (120 registered orders at three queue snapshots). Constant-score ranges,
  no eligible workshop, explicit split refusal and user-required workshops
  were also checked. The official simulator comparison includes the new policy
  in both standard and shock scenarios.
- The imported simulation completed all ten seeds (5105–5114). Its insertion
  example placed ORD-045 before ORD-109 at W6 and preserved both deadlines.
  These are simulations, not live production scheduling or guarantees.
- **Real DeepSeek smoke call passed**, using the locally inherited
  `DEEPSEEK_API_KEY` and `deepseek-flash`; no credential was printed or saved.
- **Two complete real DeepSeek workflows passed**, weighted allocation for
  ORD-045 and minimum cost for ORD-041, with 12 model calls in the final run.
  Each completed intent, extraction, three Tool stages and explanation; each
  produced the four ordered sections from the saved evidence, made no production
  write before explicit confirmation, and replayed confirmation without a second
  allocation. All calls used an isolated temporary database.
- `git diff --check` passed. Raw live reports and logs are local under ignored
  `evaluation/live_results/`; API keys and preview credentials are excluded.

## Running DeepSeek

The application reads its inherited environment once at startup. Export
`DEEPSEEK_API_KEY` in the launching terminal or use the existing private `.env`
workflow. Do not put a key in a command argument or tracked file. This machine's
key is available to interactive zsh, not the agent's noninteractive shell.

```sh
uv run --locked python -m app.server --mode llm --model-key deepseek
uv run --locked python evaluation/verify_deepseek_live.py
uv run --locked python evaluation/verify_deepseek_live.py --workflow
```

For this machine's existing environment, validation used system Python 3.14
with `PYTHONPATH=.venv/lib/python3.14/site-packages` because the virtualenv's
Python executable lacks its original standard-library installation.

New Requests sessions can use LLM / DeepSeek. Existing sessions retain their
original model/mode. Example: `Allocate ORD-045 using weighted hybrid to one
workshop.` Use `Allocate ORD-041 at the lowest cost to one workshop.` to compare
how the explanation follows a different objective.

The integration uses the provider's documented
[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
through the existing LangChain model registry. Available model identifiers can
be checked with the official [models API](https://api-docs.deepseek.com/api/list-models/).
