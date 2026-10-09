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

### MVP v0.3 会话扩展（2026-10-03）

应用发布为 mvp_v0.3；原分配入口仍输出 mvp_v0.2，以保留既有幂等指纹。migration003 新增 sessions/session_messages，独立 session_v1 接口提供消息、完整替换、确认、关闭。Parser v1 仍是单消息契约，会话命令层负责显式合并；合并结果审计需要回溯整段会话。详见 [会话契约](SESSIONS_CN.md) 和 [数据库说明](DATABASE_SCHEMA_CN.md)。

## MVP v0.4 UI 和认证扩展（2026-10-06）

发布版 mvp_v0.4 / Database v4；原 Pipeline v0.2、Parser/Prompt/Session v1 保持。004 新增账号、登录 token 哈希与 request_actors，旧迁移保持原文。HTTP 业务接口默认需要登录；actor 由服务端注入，带 actor 的请求指纹额外绑定身份。拒绝推荐为 message 动作内的显式命令，不扩展 session_messages.action 枚举。新增 dashboard/workshops/audit/export 是读取接口，详细字段和边界见 [UI/API 契约](UI_API_CN.md)。

## MVP v0.5 增量（2026-10-09）

无数据库迁移，已有版本号不变。backend 增加 `deepseek`，从服务器环境读取 Key；登录后的 `GET /api/ai/status` 只返回 backend/configured/model。

会话回合可传 `changes`，仅限 action=message 且 message 为空；白名单与类型校验后合并草稿，不调用模型。编辑对象按键排序后进入幂等指纹，并以 `Edit details: {...}` 写入用户消息，沿用 action 枚举。已有订单不能切换；未解决的业务约束继续阻止确认。

会话结果增添 `assistant_reply`（事实摘要）及 `clarifications`（code/field/question/help）。dashboard 增添 `recent_allocations`，audit 与 CSV 增添 `summary`。旧保存消息保持原文；客户端应允许历史结果没有这些增量字段。HTTP 示例见 [接口说明](UI_API_CN.md)。
