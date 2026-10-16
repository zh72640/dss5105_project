---
name: recommendation-explanation
description: Explain an existing recommendation using its saved result and current validity.
triggers: The user asks why a recommendation was made or asks about a previously shown plan.
tools: [inspect_recommendation, get_order, list_workshops, score_workshop, get_estimated_completion_time, get_lateness_score, get_defect_score, get_hybrid_score, ask_user]
---
# Recommendation Explanation

## Scope
Use for questions about a saved recommendation and its reasoning. Do not silently revise requirements or submit an allocation. A hypothetical change needs a new recommendation workflow.

## Inputs and output
Input: the current session or an unambiguous saved recommendation reference. Output: status, allocation split, objective, delivery and cost estimates, rejected candidates, and stated limitations from verified results.

## Steps
1. Call `inspect_recommendation` to obtain the saved result and current validity. If the reference is ambiguous, call `ask_user` and pause.
2. Use `get_order` or `list_workshops` only when current facts are needed to explain the result.
3. Use `score_workshop` only for an order-specific single-workshop comparison. Distinguish its original hybrid score from the planner's weighted objective.
4. Explain the saved evidence and state whether the recommendation is still valid. If stale, invite a fresh calculation.

## Failure handling
For no saved recommendation, report its absence. For stale or conflicting data, do not present the old plan as confirmable. On denied or unavailable Tools, state that the explanation is incomplete rather than inventing evidence.
