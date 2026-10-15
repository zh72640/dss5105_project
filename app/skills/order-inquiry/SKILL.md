---
name: order-inquiry
description: Answer questions about registered orders and their current production facts.
triggers: An order status, quantity, due date, or production history question.
tools: [get_order, ask_user]
---
# Order Inquiry

## Scope
Use for a question about a registered order. Do not use for an allocation recommendation, confirmation, or production write. The order ID must be explicit in the user message or unambiguous in the active task.

## Inputs and output
Input: an exact order ID. Output: the returned order state, version, total and remaining pieces, due date, and other requested recorded fields. Label missing facts as unavailable.

## Steps
1. Identify the exact order ID. If missing or ambiguous, call `ask_user` with one focused question and pause.
2. Call `get_order` for that ID. If no record exists, report that fact and ask the user to verify the ID.
3. Answer using the returned fields. Distinguish order status from any allocation recommendation; do not imply a submission.

## Failure handling
On unavailable or unauthorized Tool access, stop and report that the order could not be checked. On stale context, fetch the current order again. Do not infer order facts from conversation text.
