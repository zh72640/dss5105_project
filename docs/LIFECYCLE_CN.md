# 生产生命周期与人工操作

版本：MVP v0.2，数据库迁移 002；Parser/Prompt v1 保持原语义。此实现完成上一阶段交接的第二优先级第 1 项。以下是明确记录的实现政策，仍需团队与原 Data Schema2 核对。

## 业务操作

| 操作 | 前置状态 | 成功后状态 | 数量与队列 |
|---|---|---|---|
| complete | WORKING，指定活动工坊 | 部分完成仍 WORKING；整单完成为 COMPLETED | `pieces` 表示本次新增完工数；不得超过该工坊未完工数 |
| cancel | WORKING | READY | 撤销剩余分配，保留累计完工数，允许提交新请求再分配 |
| reassign | WORKING | WORKING | 按新约束重派全部未完工数；新方案失败时原分配完整保留 |
| lapse | READY / UNASSIGNED / WORKING | LAPSED | 显式终止后续生产，保留完工数，释放当前剩余预留，禁止再次分配 |

这里的 **cancel 是撤销当前分配**；若要让订单不可再分配，使用 lapse。已 COMPLETED 或 LAPSED 的订单不能通过这些操作恢复。没有自动完工或按交期自动失效。自然语言 Parser 仍只负责分配；人工操作通过独立结构化入口执行。

订单 `pieces` 始终是主数据总量，`completed_pieces` 为累计确认完工数。再次分配和重派仅处理 `pieces - completed_pieces`；用户自然语言中写出的订单数量仍须匹配原主数据总量。

示例：150 件分配到 W6 → 登记完成 50 → cancel → 再次分配只有 100 件 → reassign 到 W8 仍只有 100 件 → 完成剩余 100，整单状态才变成 COMPLETED。

## 一致性、审计与并发

每项操作必须提供 `actor`、`reason`、`event_id`、`expected_version`。操作人是本地调用者填写的标识，**不是已经认证的账号**。本系统仍是本机课程演示，未实现权限和身份认证。

- 先读取订单当前 version，操作时携带该值。成功分配、无可行方案进入 UNASSIGNED、成功人工操作都会增加 version；失败操作不增加。
- 同 event_id / 同参数重放已存结果；同 ID / 不同参数返回 IDEMPOTENCY_CONFLICT。分配 request_id 与事件 event_id 共用幂等命名空间。
- 新 ID 携带旧版本返回 VERSION_CONFLICT；需要重新读取并核对状态，再决定新的操作。不能盲目改版本重试。
- 在同一个 SQLite 写事务中更新订单、工作分配、队列、完工/失效表、requests、decision_log 和 lifecycle_events。
- 重派内部先释放当前预留，再计算新方案；无可行方案或写入失败会恢复旧分配和队列，不会把订单留在空档。
- lifecycle_events 保存操作人、原因、业务日期、预期版本、是否应用、完整前后状态快照。即使活动 working_order 行被移除，原分配仍可在快照及原始 decision_log 中追溯。
- 可记录的业务拒绝/事务失败同样写审计，`applied=0`。若连审计也写入失败，整笔操作回滚并返回 `error_logged=false`，不会出现业务已变但审计未落库。

## 队列算法与边界

`workshop_queue.baseline_queue_days` 表示 CSV 导入时不属于本系统分配的既有队列；每笔 working_order 增加 `queue_remaining_days` 和 `capacity_at_assignment`。总队列等于 baseline 加所有活动预留。

日历天流逝先消耗 baseline，再按分配插入顺序 FIFO 消耗各订单预留。撤销只释放该笔订单尚未随时间消耗的预留。部分完工按剩余件数和分配时产能限制预留上限，避免把“时间已经消耗的产能”再减一次，也不误删后续订单的队列。

队列是预测，不是完工证据：即使预计队列已归零，也必须登记真实 complete 才增加确认完工数。登记提前完工可能减少原预测预留；剩余运输时间不进入生产队列。未来工坊产能变更须另设管理操作，不能直接改列破坏这些关系。

业务日期倒退、队列缺行或总量与分项不一致会阻止操作；不自动猜测修复。已应用事件也禁止该订单后续事件回到更早日期。审计 UTC 时间与课程业务日期（默认 2026-04-01）分别保存。

## 旧库升级

首次打开 v1 库时，在单个事务内应用 `002_lifecycle.sql`，保留订单、队列、原请求和历史记录；不重新导入 CSV，不改已发布的 001。

旧系统仅追加队列且按日历天衰减，迁移据此从最新分配向前恢复尚未消耗的预留，剩余部分归 baseline。分配时产能采用旧库当前产能；旧系统没有产能编辑入口。若有人在数据库外手工改过历史产能或队列，应先人工核对，再升级。

原 CSV 已完成订单的 completed_pieces 初始化为总件数；其余从 0 开始，旧订单 version 从 0 开始。迁移失败会回滚 DDL/回填和迁移版本；不支持未知未来版本。运行库应先停服务并备份，验证副本后再继续使用。

## Python 入口

```python
from app.lifecycle import inspect_order, process_event

order = inspect_order("ORD-045", db_path="runtime/dispatch.sqlite3")
response = process_event(
    "complete", "ORD-045", workshop_id="W6", pieces=50,
    actor="operator-a", reason="工坊确认首批完成", expected_version=order["version"],
    event_id="production-045-001", db_path="runtime/dispatch.sqlite3",
)
```

重派可携带 `objective`、`exclusion`（W ID 数组）、`max_workshops`（1–8）、`preferred_workshop` 和 `deadline_required`；未指定时默认最快、最多 1 个工坊、软交期。它是一次完整的新约束提交，不自动继承旧请求约束；有硬性限制时需在重派表单/参数中再次明确填写。
