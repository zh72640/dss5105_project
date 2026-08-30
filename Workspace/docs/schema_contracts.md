# Week 4 schema contracts (v0.1 frozen)

These contracts are frozen for Week 4 integration. Additive changes require a
version bump; renaming or changing field meaning requires team review.

## StructuredRequest

Producer: M1 parser. Consumers: M2 conversation, M3 tools, M4 allocator.

Required contract fields: request/order identity, customer, product/category,
quantity, ISO required date, preferred/excluded workshop, objective override,
constraints, missing/ambiguous diagnostics, and raw text.

## CandidateMetrics

Producers: M3/M4 deterministic tools. Consumers: M4/M5/M6.

Includes workshop identity, eligibility and exact exclusion reason; queue,
processing, transport and turnaround days; cost and defect rate; estimated ISO
delivery date and deadline result; optional configured score.

## AllocationResult

Producer: M4/conversation gate. Consumers: M5 UI, M6 evaluation, audit log.

Includes decision status (`ALLOCATE`, `CLARIFY`, `REFUSE`, `DECLINE`, or
`ESCALATE`), recommendation, complete eligible ranking, reason codes, configured
objective, warnings, and a human-facing message.

## Failure rules

- Missing/ambiguous identity: `CLARIFY`, never guess.
- Unsupported data question: `DECLINE`, never invent.
- Ineligible preferred workshop: `REFUSE` with exact hard-rule reason.
- No eligible candidate: `ESCALATE` with options added in a later iteration.

