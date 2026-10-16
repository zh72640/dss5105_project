---
name: allocation-recommendation
description: Build an auditable allocation recommendation for an existing order.
triggers: A request to allocate, dispatch, compare allocation options, or recalculate a recommendation.
tools: [get_order, list_workshops, get_queue, score_workshop, get_estimated_completion_time, get_lateness_score, get_defect_score, get_hybrid_score, update_constraints, check_requirements, compute_plan, save_recommendation, ask_user]
---
# Allocation recommendation

## Scope and prerequisites
Use this Skill only after the Allocation preparation stage has extracted and checked
the order reference and current constraints. It guides recommendation and revision,
not allocation commitment or production events. Tools must be registered and
authorized by the runtime; this document grants no permission. The registered
order and current business database are authoritative.

## Inputs
Required: one exact order ID in the saved task and a business date supplied by the
runtime. Optional: objective, exclusions, a hard preferred workshop, workshop
limit, and hard deadline requirement. Keep saved constraints unless the user
explicitly revises them. Never silently relax a hard constraint.

## Workflow
1. **Check context → use saved task and get_order when needed → identify the
   registered order and any user constraints.** Use update_constraints only for a
   change grounded in the current user message. A revision invalidates the prior
   recommendation and requires fresh confirmation.
2. **Check feasibility → call check_requirements → read the authoritative report.**
   If it is blocked, ask one precise question with ask_user or report the
   blocking issue. Do not call the planner while blocked.
3. **Find a plan → call compute_plan → inspect the verified integer allocation,
   rejected workshops, cost, delivery date, and warnings.** Use list_workshops,
   get_queue, or score_workshop when a comparison needs supporting evidence.
   score_workshop's deadline-gated hybrid score differs from the planner's
   weighted hybrid objective.
4. **Handle alternatives → use the reported rejection and constraint evidence
   to compare eligible candidates or request a revised constraint.** Do not
   invent a workshop or widen a user limit. If no plan satisfies the constraints,
   report the specific issue.
5. **Save preview → call save_recommendation only after a successful compute_plan
   in this run → use its saved recommendation ID, task version and result.**
   Explain the split quantities, expected delivery, cost, objective and limits.
   Invite the user to confirm that exact card through the explicit UI action.

## Output and completion
A successful output cites the saved recommendation ID and version and explains
only fields present in verified Tool results. The result is a preview awaiting
confirmation; no production allocation or queue update occurs. Model wording
alone cannot establish completion.

## Failure handling
For missing or ambiguous order information, ask for the exact ID. For stale facts,
version changes, or an invalidated plan, rerun the checks and calculation before
saving. For unavailable or unauthorized Tools, model errors, or execution limits,
stop and report the failure without claiming a recommendation exists. A partial
comparison is not a saved recommendation.
