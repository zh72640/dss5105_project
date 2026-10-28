---
name: allocation-recommendation
description: Check prepared order facts and save one verified single-workshop recommendation.
triggers: An allocation task after LLM field extraction and deterministic database preparation.
tools: [check_requirements, compute_plan, save_recommendation]
---
# Allocation recommendation

## Scope and prerequisites
Use inside the Allocation node after fixed preparation. The database provides
authoritative order facts. Preparation may leave the task READY or RECOMMENDED.
This workflow supports one workshop. Tools remain subject to Runtime permissions
and Service validation; Skill text grants no permission.

## Inputs
The Runtime supplies skill_input containing order_id, product, pieces (registered
order total), and due_date. It also supplies the business date, objective, and
effective constraints. Preserve registered facts and saved constraints.
order_id and product must be nonempty strings, pieces a positive integer, and
due_date an ISO date (YYYY-MM-DD). Missing and invalid fields are separate errors.
The supported objectives include `weighted_hybrid`: normalized 80% signed
lateness and 20% defect exposure (`defect_rate * pieces / capacity`). It applies
to one workshop. Preserve the user's recorded objective; do not substitute this
policy for `hybrid` or infer that it optimizes cost.

## Workflow
1. **Verify delivered inputs → call check_requirements → inspect skill_input and
   the validation report.** Check order ID, product, total pieces, and due date
   again. A missing field ends the workflow with
   `Missing required field(s): {fields}.` Do not invent a value, ask a follow-up
   question, or proceed while blocked.
2. **Calculate → call compute_plan → inspect the verified allocation result.**
   Accept only one eligible workshop covering the remaining pieces. Do not
   replace a failed plan with a relaxed constraint or multiple workshops.
3. **Save → call save_recommendation → inspect the saved ID, version, status,
   and result.** A calculation alone is insufficient. The save checks fresh facts
   and must succeed in this run. Stop after success; the Runtime assembles the
   typed return from saved business records.

## Output and completion
Return order_id, product, pieces (registered total), due_date, workshop_id,
workshop_name, allocated_pieces (this plan's quantity), estimated_delivery_date,
delay_days, expected_defect_rate, estimated_cost, objective, warnings,
recommendation_id, and task_version.
When present, preserve explanation_evidence from the saved result, including
the method, score formula, candidate comparisons and queue/processing/pickup times.
The Service supplies these values. Negative delay_days means early delivery,
zero means on time, and positive means late. Quality is expected defect rate;
price is estimated total cost. Do not calculate or fabricate these fields.
The Runtime checks completion from a valid current-version saved recommendation.
This is a preview awaiting explicit confirmation. Explanation, user response
generation, and allocation submission are downstream responsibilities.

## Failure handling
Missing or invalid inputs, infeasibility, unsupported multi-workshop requests,
denied tools, and execution limits end this workflow with the specific issue.
On STALE_PLAN, repeat check_requirements, compute_plan, and save_recommendation
once. If the retry fails, stop; never reuse the old plan. Model/provider failures
retain the server's request recovery behavior. Never claim an unsaved recommendation.
