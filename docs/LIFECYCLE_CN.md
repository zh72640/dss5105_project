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

## 页面、HTTP 与 CLI

启动 `python3 -m app.server` 后，在“生产进度与分配调整”中输入订单号并读取。核对已完工/未完工数，填写操作人和原因，选择操作后保存。版本来自本次读取；网络失败重试同一操作沿用 event_id。页面下方可查看订单操作历史，完整事件响应在审计区展示。

| 接口 | 用途 |
|---|---|
| GET /api/orders/ORD-045 | 当前状态、version、活动分配和最近 30 条事件概要 |
| POST /api/events | 显式生产操作，使用与消息接口相同的 JSON 和同源要求 |
| GET /api/history | 同时展示分配请求和人工操作 |

完工请求示例（只适用于当前版本确实为 1 且 W6 已分配的订单）：

```json
{"action":"complete","order_id":"ORD-045","actor":"operator-a","reason":"工坊确认首批完成","expected_version":1,"event_id":"event-045-001","workshop_id":"W6","pieces":50}
```

必填：action、order_id、actor、reason、expected_version、event_id。complete 另须 workshop_id/pieces；reassign 才接受重派约束。HTTP 200 表示事件成功或成功重放，409 表示版本/幂等冲突或业务不允许，404 表示订单不存在，400 表示字段错误，503 表示系统错误。失败事件相同 ID 也重放原失败，修正后使用新 ID。

HTTP 业务日期由服务端 `--as-of` 控制，不接受请求自行指定数据库或日期。返回 `order` 是事件发生时的快照；若后来又有操作，幂等重放仍返回历史快照，应重新 GET 获取当前状态。

```bash
# 查询当前版本、分配及生产进度
python3 -m app.lifecycle_cli inspect ORD-045

# 下面的版本值和工坊必须按实际查询结果填写
python3 -m app.lifecycle_cli complete ORD-045 --workshop-id W6 --pieces 50 \
  --actor operator-a --reason '工坊确认首批完成' --expected-version 1 --event-id event-045-001

# 使用单独的持久化临时数据库，一次演示完整流程，不改 runtime
python3 -m demos.lifecycle_demo
```

CLI 支持 `inspect/complete/cancel/lapse/reassign`、`--db`、`--as-of`；重派约束为 `--objective`、可重复的 `--exclude`、`--max-workshops`、`--preferred-workshop`、`--deadline-required`。成功或成功重放退出 0；业务拒绝/系统错误退出 1；缺必填命令行参数退出 2。

## 本轮验收

专项测试覆盖部分完工、拆单完工、撤销后只重派剩余数量、失效、重复事件、跨接口 key 冲突、并发同 key、并发不同操作争用版本、日期倒退、队列 FIFO 衰减和避免重复扣减、缺失队列、重派中途失败、审计失败、旧库升级/重复打开/迁移回滚/未知版本，以及真实 HTTP 和 CLI 流程。

2026-10-02 在 Chrome 对独立 `/tmp` 数据库实际提交 ORD-045：分配 W6 150 件 → 完成 50 件 → 重派 W8 100 件 → 刷新页面仍保留进度 → 完成 100 件。页面最终显示 COMPLETED、150/150、剩余 0、版本 4；历史显示 COMPLETE / REASSIGNED 等记录。操作人/原因必填也实际触发并验证。界面检查修复了切换操作时隐藏字段仍占位的问题。
