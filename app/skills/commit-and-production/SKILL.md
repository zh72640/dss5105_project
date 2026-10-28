---
name: commit-and-production
description: Guide explicit recommendation confirmation and audited production actions.
triggers: The user requests confirmation, completion, cancellation, lapse, or reassignment.
tools: [inspect_recommendation, get_order, record_production_event, ask_user]
---
# Commit And Production

## Scope
Use for explicit recommendation confirmation guidance or audited production events. A conversational request to confirm is guidance only; the server's explicit confirm action performs allocation submission. Production events require an explicit current user request.

## Inputs and output
Confirmation needs the exact valid recommendation ID and current session version in the UI action. Production events need action, order ID, expected order version, audit reason, and action-specific fields. Output is the saved confirmation result or the recorded event result, never model wording alone.

## Steps
1. For confirmation, call `inspect_recommendation` if validity is unclear. Direct the user to confirm that exact card through the UI. The server rechecks owner, versions, business facts, and plan in one transaction.
2. If the message revises any requirement, use the revision Skill first and request confirmation of a new card.
3. For a production event, call `get_order` for its current version. Verify that the user explicitly stated the order, action, reason, and any completion workshop and quantity. If details are missing, call `ask_user` and pause.
4. Call `record_production_event` only with explicit details. Report the returned success, refusal, or version conflict accurately.

## Failure handling
On stale recommendation, version conflict, unauthorized request, or Tool failure, do not claim a submission. Ask for the missing detail or a fresh recommendation. A partial event is not a successful event; the lifecycle service and database audit are authoritative.
