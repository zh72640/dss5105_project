# 数据库映射、事务及状态语义

数据库版本 3，迁移文件为 `001_initial.sql`、`002_lifecycle.sql` 和 `003_sessions.sql`。采用 Python 标准库 SQLite。目录中没有 **Data Schema2 原始文件/DDL**；当前结构依据 Week 5/6 计划并增加生命周期和会话扩展，不能宣称与尚未提供的原库完全兼容。

## 表与数据来源

| 表 | 用途 / 进入条件 |
|---|---|
| schema_migrations | 逐次记录迁移版本；遇到未知版本停止，避免误用 |
| orders | 原始 CSV 120 行；保留 source_status，另加 state/version/completed_pieces |
| workshops | 原始 8 个工坊的能力、价格、缺陷、状态及批量限制 |
| workshop_queue | 每工坊 1 行，current_queue_days + baseline_queue_days + as_of_date；初始日期 2026-04-01 |
| requests | request_id、时间、原始消息、指纹、返回值、telemetry；会话请求填写 session_id，其他入口为 NULL |
| request_parsing_history | 单消息存校验后的 ParseResult；会话存合并草稿，字段证据沿 session_messages 与 telemetry 回溯 |
| working_order | 每活动订单/工坊 1 行；sum(pieces-completed_pieces) 加订单累计完工数等于订单总数；保留分配时产能和未消耗预留 |
| decision_log | 每请求 1 行；结果、目标、reason codes 和完整机器决策 |
| unassigned_order | 订单有效但无可行分配，或指定工坊不能接单；每订单保留最近失败 |
| completed_order | 导入源 CSV 的 86 个 COMPLETE 订单；后续全部完工时新增，禁止重分配 |
| lapsed_order | 显式 lapse 事件写入；不按日期自动写入 |
| lifecycle_events | actor/reason/action/as_of_date/expected_version/applied 与前后完整快照；关联 requests/decision_log |
| sessions | state/version、固定配置、draft_json、blockers_json、reviewed_order_version、创建/更新时间 |
| session_messages | session_id/sequence 联合主键，每回合 user/assistant 两条；关联唯一 request_id/role |

`workshops.current_queue_days` 规范化到 `workshop_queue`，仓储通过 join 返回实时队列；避免同一队列在两张表中出现不同值。

## Parser → request_parsing_history

| Parser | 数据库列 |
|---|---|
| order_id | parsed_order_id |
| customer | parsed_customer |
| product | parsed_product |
| category | parsed_category |
| pieces | parsed_pieces |
| order_date | parsed_order_date |
| due_date | parsed_due_date |
| objective | parsed_objective |
| exclusion | parsed_exclusion，JSON ID 数组 |
| num_workshop_allowed | parsed_num_workshop_allowed |
| preferred_workshop | parsed_preferred_workshop，兼容扩展 |
| deadline_required | parsed_deadline_required，兼容扩展 |
| parse_status / missing_fields / ambiguities | 同名运行诊断列；后两项为 JSON 数组 |

request_id、request_date_time、original_message 由服务端提供。解析阶段缺失的字段保持 NULL；数据库订单补全只发生在 trace.order 和业务计算中，不倒填 parsed_*。

## 检索和状态规则

本版批准的检索规则是 **order_id 精确匹配**。客户/产品组合检索可日后扩展；当前缺 ID 一律 CLARIFY，多 ID 不猜。若消息明确写出的 customer/product/category/pieces/order_date/due_date 与数据库不一致，返回 ORDER_FIELD_CONFLICT 并要求核对，不修改订单主数据。无对应订单返回 DECLINE / ORDER_NOT_FOUND，保留 Week 4 R18 语义。

源 `IN_PROGRESS` 在本系统初始为 READY，并非已经外包分配；只有本系统成功写入 working_order 后才为 WORKING。

| state | 语义 | 再次分配 |
|---|---|---|
| READY | 原始生产未完成，或已撤销剩余分配 | 可以 |
| WORKING | 已成功外包分配，队列已计入 | 禁止，防止重复计量 |
| UNASSIGNED | 有效但当前没有可行方案 | 可以，用新的 request_id 重试 |
| COMPLETED | 原数据或登记生产已全部完成 | 禁止 |
| LAPSED | 显式 lapse 终止生产 | 禁止；cancel 撤销分配返回 READY，不是 LAPSED |

**逾期不自动失效。** 原课程数据中多条正常请求已经逾期，Week 4 标签仍要求分配。因此 due_date 默认是目标交期，逾期/预计迟交产生 warning；只有 deadline_required=true 才将日期作为硬约束。是否未来引入自动 lapsed、工作日历、改单审批，需要团队确认。

## 分配与时间

资格顺序：用户排除 → ACTIVE → category/makes → max_batch；capacity 必须为正。单工坊按整单检查 max_batch，多工坊按分配片段检查。指定 preferred_workshop 时，其必须接收整单；不会悄悄改派或拆给别人。

- 未指定最大工坊数时为 1；指定 N 时为最多 N，可能只用一个工坊。
- 当前数据只有 8 个工坊；枚举候选组合。min_cost 和 min_defects 按单件指标分配，min_delay 使用整数容量下的最早整体完成时间。小规模样例已用穷举对照验证这三个目标。
- hybrid 使用 `0.6 * days + 0.4 * expected_defect_rate * 100` 对候选组合的速度拆单打分，是启发式策略，未声称求得全局最优。
- processing_days = pieces / capacity；estimated_days = queue + processing + transport。
- 队列增加 **processing_days**，不增加 transport；每个已选工坊同时更新 as_of_date。查询未来业务日期时扣除经过的日历天，最低 0；业务日期倒退报 QUEUE_DATE_REWIND；缺队列记录报 QUEUE_DATA_MISSING，不默认为空闲。
- 页面日期按 `ceil(estimated_days)` 保守显示。官方模拟器原本使用 round，保持原样；因此系统展示日期与模拟器的整数天结果可能相差一天。暂不建模周日停工或随机返工，缺陷率为预期指标。

## 原子写入与幂等

解析在 SQLite 写锁外执行。随后 `BEGIN IMMEDIATE` 下重新检查 request_id，完成 request/parsing/decision、working_order、queue、orders.state 和 unassigned 清理，最后一起 COMMIT。两个并发请求可以都完成解析，但同一 ID 最多提交一次。

request_id 是幂等 key：同 key + 同消息/默认目标/日期/backend/model/版本 → 重放原结果；同 key + 不同输入 → ERROR / IDEMPOTENCY_CONFLICT（HTTP 409）。新 key 申请同一 WORKING 订单也会被状态保护阻止。

SQL/队列错误时整个业务事务 ROLLBACK，再尝试单独保存 ERROR 审计；若数据库本身不可用，返回 error_logged=false，此时调用方应保存响应，不能承诺数据库里一定有日志。parser_error 的非法输出不进入 request_parsing_history，只进入 requests.telemetry_json；不发生分配。

失败请求的 key 也会缓存其最终结果；解决工坊/数据/LLM 问题后用**新的 key**重试。不要误用 R09 这样的样例标签作为跨不同消息的固定 key。

## 迁移和恢复

首次建库在同一事务内导入 CSV 并运行 001–003；旧 v1 按顺序应用 002/003，旧 v2 应用 003，v3 直接使用。迁移不重复导入、不重置队列，失败回滚；后续变化新增 004，不改已发布迁移。

当前已支持显式撤销分配、完工、失效和重派；主数据改单尚未实现。需要回到干净演示环境时，优先使用 `python3 -m demos.week6_demo` 或另一个 `--db` 文件；不要只删除 working_order 行，因为队列和订单状态必须同步恢复。

## v0.2 生命周期补充

具体状态转换、部分完工数量守恒、FIFO 预留衰减、旧库回填假设、版本冲突与审计失败回滚见 [生命周期手册](LIFECYCLE_CN.md)。原 request_parsing_history 字段和 Parser/Prompt v1 未改；人工事件通过结构化参数进入，保存 requests/decision_log/lifecycle_events，不伪造解析历史。

版本由 mvp_v0.1 升至 mvp_v0.2，分配幂等指纹包含版本；v0.1 的分配 key 用于新版请求会返回 IDEMPOTENCY_CONFLICT。原响应仍保存在 requests，升级后新的分配应使用新 key，WORKING/COMPLETED/LAPSED 仍受状态保护。

## v0.3 会话补充

应用发布版本为 v0.3，但原分配 Pipeline 保留 v0.2，使既有 v0.2 key 可继续重放。session_v1 使用独立指纹（会话 ID、预期版本、动作、消息），与其他操作共享 requests 主键。会话确认复用 `_decide/_apply/_record`，未修改分配算法；所有会话记录与生产变更在同一事务内提交。草稿和失败确认不写 working_order/queue/unassigned_order。

`requests.session_id` 是早期预留的 TEXT；003 保持该列不变，通过写入路径保证关联。session_messages 的外键约束连接 sessions 与 requests。会话 SQL 故障回滚所有审计和状态，不像单消息路径另写最佳努力错误记录，调用方保留响应并用原 key 重试。完整边界见 [会话手册](SESSIONS_CN.md)。
