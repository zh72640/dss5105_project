---
name: workshop-inquiry
description: Inspect workshop eligibility, capacity, queues, and original scoring metrics.
triggers: A workshop question or a request to compare workshop timing or quality.
tools: [list_workshops, get_queue, score_workshop, ask_user]
---
# Workshop Inquiry

## Scope
Use for questions about registered workshops, queue timing, capacity, quality, or original single-workshop scores. Do not use a single score as a complete allocation recommendation or as confirmation.

## Inputs and output
Input: an optional workshop ID; `score_workshop` also requires an exact order ID and may use an explicit positive batch quantity. Output: current recorded workshop fields and, when requested, queue or score metrics with their business-date context.

## Steps
1. Call `list_workshops` to identify registered resources. If the requested ID is missing or ambiguous, call `ask_user` and pause.
2. Call `get_queue` for current queue timing when relevant. For an order-specific comparison, call `score_workshop` with the exact order and workshop IDs.
3. Explain capacity, eligibility rejection, timing, lateness, and defect metrics from Tool output. State that the original deadline-gated hybrid score differs from the planner's weighted hybrid objective.

## Failure handling
For missing records, ask for valid IDs. For stale data, fetch again. If a Tool is unavailable or denied, report the limited facts obtained and stop. Never invent a queue or candidate score.
