---
name: constraint-revision
description: Apply a grounded requirement change and invalidate an affected recommendation.
triggers: The user changes quantity, objective, deadline, excluded or preferred workshops, or a workshop limit.
tools: [update_constraints, check_requirements, compute_plan, save_recommendation, ask_user]
---
# Constraint Revision

## Scope
Use when the user explicitly changes an active allocation requirement. Exclude read-only questions and confirmation alone. A revision invalidates the prior recommendation and requires a new explicit confirmation.

## Inputs and output
Input: a named field and a value or supported set, unset, add, remove, or undo operation grounded in the current message. Output: the changed draft and task version; if feasible, a new saved recommendation ID and plan result.

## Steps
1. Identify each explicit change and call `update_constraints` for one supported requirement at a time. If the message is ambiguous, call `ask_user` before changing state.
2. Call `check_requirements` after the revision. If blocked, explain the exact issue and ask for the required correction.
3. When ready, call `compute_plan`; inspect the verified result and warnings.
4. Call `save_recommendation` only for a plan computed in this run. Explain which recommendation is now valid and ask for a fresh explicit UI confirmation.

## Failure handling
A rejected or ungrounded change leaves the prior state authoritative; report the Tool error. For stale facts, rerun checks and planning. If any Tool is denied or unavailable, stop without claiming the revision or recommendation succeeded.
