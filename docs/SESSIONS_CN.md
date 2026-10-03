# 多轮澄清与分配确认

更新：2026-10-03；契约 `session_v1`；数据库 migration 003。

## 使用流程

新建会话 → 输入分配需求 → 补订单号 → 修改约束 → 核对草稿和候选 → 确认分配。

例如依次发送：`Allocate cheapest; exclude W03.`、`ORD-045`、`改成两个工坊`、`不要 W6`、`取消刚才的排除`、`不要 W3`。发送和修改只保存草稿；显式确认才写入生产分配和队列。成功分配后会话 CLOSED，其他订单需新建会话。

## 接口契约

- `create_session(session_id, objective, backend, as_of)`：同 ID、同配置返回现有会话；不同配置返回冲突。业务日期、解析 backend 和默认目标在创建时固定。
- `inspect_session(session_id)`：返回草稿、blockers、状态、版本和按 sequence 排序的用户/系统消息。
- `session_turn(session_id, expected_version, request_id, action, message)`：action 为 message、replace、confirm、close。confirm/close 必须传空消息，避免确认时遗漏新约束。
- 每个已保存回合版本加 1，写入两条消息（user/assistant），每条关联本回合 request_id。request_id 与原分配及生命周期接口共享幂等空间。
- 同 key 同输入返回原响应，即使会话已经关闭；同 key 不同输入报错。版本过期在写入前拒绝，不消耗回合；网络失败后可原 key 重试。
- 首条 message 和 replace 调用原单消息 Parser v1。后续 message 只使用完整匹配的命令语法，不拼接历史文本。`context_messages` 仍保持 v1 原行为。

## 支持的后续回复

| 目的 | 示例 | 合并规则 |
|---|---|---|
| 补订单号 | ORD-045 / 订单号：ORD-045 | 已绑定订单不可改为另一个订单 |
| 最大工坊数 | 改成两个工坊 / at most two workshops | 覆盖上次上限，范围 1–8 |
| 增加排除 | 不要 W3 / exclude W03 | 加入集合并规范化 W03 → W3 |
| 移除单个排除 | 恢复 W3 / unexclude W3 | 仅移除指定工坊 |
| 清空排除 | 取消刚才的排除 / clear exclusions | 清空全部排除，而非仅撤销最后一次 |
| 改目标 | 最快 / 最低成本 / 最低缺陷 / 平衡 | 替换目标，英文 fastest/cheapest/lowest defects/hybrid 也支持 |
| 取消指定工坊 | 取消指定工坊 / clear preferred workshop | 清空 preferred_workshop |
| 改交期约束 | 必须准时 / 允许迟交 | 设置或清除硬交期 |

每条回复一次修改。含额外文字、复合约束或不支持的表达返回 UNSUPPORTED_REPLY，并阻止确认旧草稿。下一条有效修改可解除该回复错误；初始请求的歧义必须用 replace 完整重填。替换会清除未重新写出的旧约束，UI 应明确提示。

## 状态和一致性

- AWAITING_CLARIFICATION：缺订单、歧义、无法分配或回复错误；不能确认。
- ACTIVE：当前数据下存在可行预览；可继续修改或确认。
- CLOSED：已确认分配或主动结束；只允许读取和原 key 重放。

预览只查询，不修改 orders/working_order/workshop_queue/unassigned_order。确认在锁内重新检索资格和队列、重新计算方案，因此其他订单占用队列后最终结果可能不同于预览。目标订单版本自上次预览发生变化时拒绝确认，需要重新修改/预览。部分完工后仍按现有规则只分配未完工数量。

解析在写锁之外；提交前重查会话版本和 request_id。回合消息、草稿、requests、解析/决策审计、分配与队列在同一事务中保存。任何 SQL 失败全体回滚，错误响应可原 key 重试；此路径不会另写部分会话审计。`field_sources` 记录基准会话版本、原回复、动作及合并草稿；合并草稿字段的证据来自整段已记录的会话，不能当作当前单句模型输出评价。

## 验证与限制

页面入口为“多轮澄清与分配确认”。新建会话使用页面选择的默认目标；恢复会话可粘贴 session_id。刷新后恢复最近会话、消息和上次预览/分配结果。未确认收到响应的操作保存于本浏览器 localStorage；此时需先点击“重试上次操作”，避免产生新的请求 ID。确认时使用预览时的会话版本；跨客户端修改返回 409，再恢复最新会话。

HTTP：`POST /api/sessions` 创建（可传 session_id/objective）；`GET /api/sessions/{id}` 恢复；`POST /api/sessions/{id}/turns` 传 request_id、expected_version、action、message。backend/业务日期由服务配置控制；会话创建后固定。返回 400 参数错误、404 不存在、409 版本/幂等/已关闭冲突、503 数据库错误。普通澄清返回 200，但 `committed=false`。

CLI 示例（重复执行请使用新的会话/请求 ID，或先 inspect 读取原会话状态）：

```bash
python3 -m app.session_cli --db runtime/session-demo.sqlite3 create --session-id tutorial
python3 -m app.session_cli --db runtime/session-demo.sqlite3 turn tutorial --expected-version 0 --request-id tutorial-1 --message 'Allocate cheapest; exclude W03.'
python3 -m app.session_cli --db runtime/session-demo.sqlite3 turn tutorial --expected-version 1 --request-id tutorial-2 --message 'ORD-045'
python3 -m app.session_cli --db runtime/session-demo.sqlite3 turn tutorial --expected-version 2 --request-id tutorial-3 --message '改成两个工坊'
python3 -m app.session_cli --db runtime/session-demo.sqlite3 turn tutorial --expected-version 3 --request-id tutorial-confirm --action confirm
python3 -m app.session_cli --db runtime/session-demo.sqlite3 inspect tutorial
python3 -m demos.session_demo
```

CLI 成功保存草稿（含待澄清）返回 0；错误/拒绝/不可行返回 1，脚本仍需读取 JSON 的 committed 判断是否执行分配。`demos.session_demo` 每次新建独立临时持久库，可反复演示，不依赖上面 tutorial 库。

`python -m unittest discover -s tests -p test_sessions.py -v` 覆盖多轮、替换、歧义、隔离、订单改动、部分完工、并发确认、消息审计故障回滚、进程重开、v2→v3 迁移及失败回滚。

2026-10-03 本机 Chrome 实际验收：缺订单请求 → ORD-045 → 改成两个工坊 → 排除 W8 → 刷新，恢复 ACTIVE/version4、W3/W8 排除和 GiantWeave 150 件预览 → 确认，CLOSED/version5；读取订单为 WORKING/version1、W5/150 件。使用独立 /tmp 数据库，未写入用户 runtime。HTTP/CLI 测试另外覆盖版本冲突、重放和关闭保护。

会话是显式状态机与有限命令语法，不宣称支持任意多轮自然语言。没有身份认证；隔离指状态和数据隔离，不是访问权限隔离。LLM 初始解析与 replace 仍受现有在线限流限制。
