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


## Week 5/6 migration note (2026-09-14)

The contracts above remain the **historical Week 4** contracts. The active entry
point is now `app.pipeline.process_request()`, producing a versioned v0.1 envelope
with `parsed`, `parser_telemetry`, `trace`, and `result`. The new frozen ParseResult
lives in `app/schemas/parser_schema.py`; see [Parser v1](../README_parser.md).

Week 4 `StructuredRequest`/`CandidateMetrics`/`AllocationResult` and legacy tools
remain available for historical fixtures and baselines. Do not pass ParseResult to
the old `conversation.gate_request()`; use the new pipeline, or explicitly use
`fake_parse_request()` for the old fixture contract. `result` now includes integer
`allocation` parts, success/status, rejected reasons and queue/database traces.

## MVP v0.2 增量（2026-10-02）

以上为历史契约。当前分配入口输出 mvp_v0.2，Parser/Prompt v1 不变。数据库迁移 002 增加累计完工、版本、FIFO 预留和 lifecycle_events；生产操作由 `app.lifecycle.process_event()` 提供独立结构化接口，详见 [生命周期手册](LIFECYCLE_CN.md)。活动分配未完工件数加已确认完工数守恒，不再要求部分完工后的活动 working_order.pieces 总和始终等于原订单总量。
