# 英文界面操作与课程演示指南

本指南对应 MVP v0.5。先按 [部署说明](DEPLOYMENT_CN.md) 启动服务，再打开 <http://127.0.0.1:8000>；已有账号无需重建。界面为英文，无 DeepSeek Key 时默认离线规则解析，业务日期固定为课程数据使用的 `2026-04-01`。完整新版演示见 [v0.5 测试流程](V05_TEST_WALKTHROUGH_CN.md)，模型配置见 [DeepSeek 本机接入](DEEPSEEK_SETUP_CN.md)。

顶部 **Small / Medium / Large** 一键切换字号，刷新后保留。Overview 的 **What was assigned?** 用自然语言显示最近五条审批分配：订单、工坊、件数、日期、费用和逾期提示。这些是历史决策，最新生产进度请看 Production。

## 1. 登录与首页

输入通过 `python -m app.auth 用户名` 创建的账号和密码，点击 Sign in。没有账号时页面会提示先完成本机账号设置。退出用右上角 Sign out；有尚未确认的请求时，先用 Retry safely 恢复结果。

首页 Overview 的统计有明确口径：

| 指标 | 计算方式 |
|---|---|
| Pending requests | 未关闭且可处理的会话，加上没有开放会话代表的 READY/UNASSIGNED 订单；空白新会话也算待办 |
| Needs clarification | 已产生回合、状态为 AWAITING_CLARIFICATION 的开放会话 |
| Allocated today | 按真实 UTC 日期统计决策日志中 ALLOCATE 的不同订单；重派不计为首次分配 |
| Lapsed orders | 当前状态为 LAPSED 的订单总数 |
| In production | 推荐页显示当前 WORKING 订单数，不是历史累计分配次数 |

这是“待处理订单 + 开放请求”的工作队列，不是全部 120 个订单，也不是原始课程 `dispatch_requests.txt` 的自动导入列表。初始库有 34 个未完成订单，其余为课程已完工记录。同一订单若存在多个开放会话，会分别显示；其他会话的旧确认受订单版本保护。

业务日期决定队列衰减与 ETA；审批时间来自真实系统 UTC。首页明确显示这两个日期，二者通常不同。其他时间按浏览器本地时区显示，导出保留 ISO 时间及偏移。

搜索订单号或客户可缩小 Inbox queue。View details 会恢复已有会话；无会话的待办订单会创建一个“Allocate ORD-xxx.”预览。该操作不写生产分配。Show more 展开更多待办，右侧 Workshop pulse 展示全部工坊。

## 2. 输入和澄清

点击 New request，在 Dispatch request 输入：

```text
Allocate cheapest; exclude W3.
```

选择默认目标，点击 Get recommendation。由于缺少订单号，页面显示 Needs clarification，Accept allocation 不可用。

在 Clarify or update the request 输入：

```text
ORD-045
```

点击 Send update。程序从数据库补充客户、产品、件数和交期，给出候选工坊和推荐。此时可以刷新页面，草稿、对话和预览仍在。离线规则解析以课程英文请求为主，不能保证理解任意自然语言。

可用的单项后续修改包括：

| 输入 | 结果 |
|---|---|
| `cheapest` / `fastest` / `lowest defects` / `hybrid` | 修改目标，也可以直接选择 Objective |
| `use two workshops` | 允许最多两个工坊拆分 |
| `exclude W3` | 增加工坊排除 |
| `clear exclusions` / `unexclude W3` | 清除全部或指定排除 |
| `must arrive on time` / `allow late delivery` | 启用或取消硬交期 |
| `clear preferred workshop` | 取消指定工坊 |

不清楚如何补充时，点击 **Edit details**：选择订单、目标、最大工坊数、偏好工坊、排除与交期，再点 **Update recommendation**。缺失项会显示具体问题和操作提示；登记信息冲突时可选 **Use registered order details**。此表单无需 AI。DeepSeek 会话还支持自然语言追加并保留未提及的旧要求。

需要整体重写时，在输入框中写完整请求，再点击 Replace full request。例如：

```text
Allocate ORD-045 to Nimble Needle.
```

替换会清除没有重新写出的约束，必须继续提供同一订单号。切换订单应选择队列另一条记录或新建请求。关闭一个未分配的会话不会删除订单，因此它仍可能作为待办订单出现在首页。

## 3. 查看、拒绝或接受推荐

推荐卡首先显示自然语言回复，标明 **Proposed — awaiting your approval** 或 **Approved and saved**，列出工坊、件数、预计日期、费用及关键警告。原始字段、对话和 **Calculation & eligibility details** 默认折叠，需要时展开。费用沿用课程数据单位，因此标为 Cost units，没有擅自指定 SGD/USD。

Candidate workshops 展示单工坊候选的 ETA、费用和缺陷率。允许拆单时，最终推荐可能是多个工坊的组合，不能把单工坊候选表视为所有组合方案。Eligibility checks 列出可考虑的工坊和被排除原因。

Proceed with reasoning 打开解释页面。完成时间为排队 + 生产 + 取件时间，多工坊方案使用最慢一部分的完成时间；日期向上取整到日历天。软交期晚于预计完成时只提示，Hard deadline 才强制约束。

Reject & revise 会记录拒绝、打开新的修订窗口；输入同一订单的完整新请求后，点击 Review revised request。拒绝本身不会分配，也不会自动关闭整个会话。

Accept allocation 才提交生产分配。程序使用最新队列重新计算，所以最终方案可能与先前预览不同；订单自身版本变化则拒绝旧确认并要求重新预览。接受后回到 Recommendations，显示 Approved 和 Next request。页面刷新、重复确认或网络重试不会重复增加分配。

## 4. 查询与导出历史

打开 Allocation history，按订单/请求 ID 或状态筛选。每页 15 条，使用 Previous / Next 翻页。

View record 包含原始消息、消息时间、解析字段、推荐、依据、操作者及批准时间。会话记录中的 Original message 保留首次输入；Full decision record 的 turn_message 保存该次澄清、替换或确认输入。审批人缺失的旧数据明确标记为 Not recorded (legacy)。

Export all · CSV 和 JSON 导出数据库中全部决策，包含澄清、拒绝、预览、接受及生产事件；不受当前筛选和分页影响。CSV 对可能作为公式执行的单元格加前导单引号，JSON 保留原文。需要在程序中再次分析时优先使用 JSON。

## 5. 查询工坊

Workshop explorer 支持名称或 ID、Active/Suspended/Closed 状态和 Tops/Accessories 能力筛选。Explore 展示日容量、批量上限、排队天数、取件时间、成本、缺陷率、备注和活动订单。

当前数据中的 W7 为 Suspended，W8 最大批量为 300 件。队列同时包含导入的基线工作量和系统内活动分配，因此“没有具名订单”不等于队列为零。此页面只查询，不修改工坊产能或状态。

## 6. 更新生产进度

Production 输入订单 ID，点击 Load current order。选择操作并填写 Reason：

- Record completion：选择分配工坊，填写本次新增完工件数，不填累计数。
- Cancel allocation：释放未完工分配、保留已完工件数，订单可再次分配。
- Reassign remaining pieces：按新约束重派剩余数量。新方案不可行时保留原分配。
- Lapse order：终止订单，之后不可再次分配。

点击 Review production change 核对，再点击 Confirm change。操作者来自登录用户。若提示版本冲突，重新加载订单再决定，不能通过修改 expected_version 强行覆盖。

## 7. 约五分钟演示顺序

使用专用演示库，避免修改日常工作库：

```bash
python -m app.auth presenter --db runtime/ui-demo.sqlite3
python -m app.server --db runtime/ui-demo.sqlite3 --port 8001
```

1. 登录并介绍 Overview 四个指标、业务日期和工坊队列。
2. New request 输入 `Allocate cheapest; exclude W3.`，展示无法直接接受。
3. 补充 `ORD-045`，展示原文、字段、FreshStart 推荐和候选比较。
4. 打开理由页，Reject & revise 输入 `Allocate ORD-045 to Nimble Needle.`。
5. 核对 Nimble Needle，Accept，进入历史查看自己的审批姓名和时间。
6. 在 Workshop explorer 找到 Nimble Needle 的 ORD-045，再到 Production 记录 50 件新增完工，展示保留的剩余数量。
7. 导出全部历史。结束时说明这次展示是离线链路；DeepSeek 真实调用尚待本机 Key 验收，Gemini 历史全量验收仍受配额问题影响。

已接受的订单不能重复用于首次分配演示。下次演示用新的数据库文件名，或通过正常 Cancel allocation 释放未完工分配，不删除正式运行库。
