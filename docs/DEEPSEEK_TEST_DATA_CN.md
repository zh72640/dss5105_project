# DeepSeek 模式测试流程与现有订单数据

数据核对：2026-10-09，新加坡时间。针对当前 `runtime/dispatch.sqlite3`；业务日期仍为课程日期 `2026-04-01`。下面的预期值由只读数据库查询和本地分配器计算，不代表已通过真实 DeepSeek 验收。

## 启动与接入检查

在**已配置 Key 的同一个终端**执行，保持终端打开：

```zsh
cd "/Users/moxit/Desktop/NUS/Semester 1/DSS5105/Final_Project/Project/Workspace"
export DEEPSEEK_API_KEY
.venv/bin/python -m app.server --backend deepseek
```

`export` 只把已有变量传给子进程，不打印 Key。另一个终端或 Codex 进程不会自动继承该终端的临时环境变量。若变量尚未设置，先按 [本机密钥配置](DEEPSEEK_SETUP_CN.md) 非回显输入。8000 端口被占用时先停止同项目旧服务；不要同时启动两份。

浏览器打开 `http://127.0.0.1:8000`，使用已有账号登录。页面应显示 DeepSeek；登录后打开 `/api/ai/status`，应有 `backend=deepseek`、`configured=true`。这只证明服务读到了配置，成功返回下一步的模型解析结果才证明实际接口可用。

必须点击 **New request** 创建新会话；旧 offline 会话不会自动切换。业务日期是课程数据日期，不要用电脑的十月日期推算交付时间。

## 可直接使用的数据

| 订单 | 客户 | 产品 | 数量 | 登记交期 | 核对时状态 | 用途 |
|---|---|---|---:|---|---|---|
| ORD-063 | Loom & Leaf | Cardigan | 100 | 2026-04-29 | READY | 主流程、自然语言追加、审批 |
| ORD-035 | Loom & Leaf | Beanie | 300 | 2026-04-29 | READY | 缺订单澄清、工坊能力冲突 |
| ORD-024 | Loom & Leaf | Vest | 300 | 2026-04-15 | READY | 数量冲突与表单修复 |
| ORD-109 | Harbor Knits | Vest | 500 | 2026-04-13 | READY | 工坊批量限制 |
| ORD-093 | Maple & Co | Beanie | 100 | 2026-03-29 | READY | 无法满足硬交期 |

原先示例 ORD-045 已是 WORKING，本次不要拿它重复执行首次分配。上表订单在测试过程中接受后也会变为 WORKING；后续测试先检查当前状态。

## 主流程：推荐 → 追加要求 → 保存 → 查看结果

1. 点击 **New request**，粘贴：

   ```text
   Allocate ORD-063 at the lowest cost; exclude W3.
   ```

   预期解析为 ORD-063、Lowest cost、排除 W3。核对时推荐 **FreshStart / W8，100 件，100.00 cost units，2026-04-04**。页面应为 Proposed — awaiting your approval，此时尚未分配。

2. 在追加要求框输入：

   ```text
   Please prioritize speed and use W6 for this order.
   ```

   预期目标变为 Fastest completion、偏好 W6，保留 ORD-063 和排除 W3。核对时方案为 **Nimble Needle / W6，100 件，120.00 cost units，2026-04-05**。这是复合自然语言追加，应通过 DeepSeek 解析。

3. 展开 **Request details & conversation**、**Calculation & eligibility details**，对照订单、目标、排除、数量、工坊和成本。点击 Large，再刷新，检查字号与草稿保留。
4. 核对后点击 **Accept allocation**。这一步会真实写入当前测试使用的数据库；回复应变为 Approved and saved，不能重复接受。
5. 返回 Overview，检查 **What was assigned?**；打开 Allocation history 检查审批人和时间；Production 加载 ORD-063，检查 W6 的 100 件分配。
6. 可选：Production → Record completion，工坊 W6，Newly completed pieces 填 `50`，Reason 填 `Course demo: first batch completed`。预览并确认后，应显示已完成 50、剩余 50，仍为 In production。

日期和工坊队列会随其他审批改变；以确认时最终结果为准。成本单位来自课程数据，不代表 SGD/USD。

## 追加测试：每组使用 New request

### A. 不知道缺什么

```text
Allocate at the lowest cost.
```

应明确询问订单号，Accept 不可用。回复 `ORD-035`，或通过 Edit details 选择该订单，应进入可审核推荐；无需猜测产品和数量。

### B. 数量与登记不一致

```text
Allocate ORD-024 999 pieces at the lowest cost.
```

应提示登记数量是 **300**，不能直接接受。选择 **Use registered order details** 并点 Update recommendation，数量应恢复为 300；订单主数据不被修改。

### C. 指定工坊不能加工产品

```text
Allocate ORD-035 to W3.
```

W3 只做 TOPS，不能接 Beanie / ACCESSORIES。应说明能力不匹配并引导改偏好。Edit details → Preferred workshop → Any eligible workshop，更新后重新推荐。

### D. 指定工坊超出批量上限

```text
Allocate ORD-109 to W8.
```

订单 500 件，W8 上限 300；应提示超限。清除 Preferred workshop 后，按需允许最多两个工坊，再生成方案。仅增大工坊数而保留指定 W8，仍不会绕过上限。

### E. 无法满足硬交期

```text
Allocate ORD-093. It must arrive on time.
```

登记交期 2026-03-29 早于业务日期 2026-04-01，应提示无法准时。若演示允许迟交，可关闭 Hard deadline；随后推荐应保留迟交警告。

### F. 当前业务不支持的要求

```text
Allocate ORD-024 with a budget of 100.
```

预算上限尚不支持，应明确说明并阻止接受。用 Replace full request 重写为 `Allocate ORD-024 at the lowest cost.`；如果此前已审批该订单，改用其他 READY 订单。

## 判断测试结果

- Key 缺失、认证失败、余额不足、限流和连接异常，应显示 AI 服务问题，不应要求补订单资料。
- 模型理解未达到预期时，先检查 Parsed request；记录输入和错误名称即可，不记录或发送 Key。
- Edit details 不依赖模型，能用于修正支持的业务字段；它的成功不能当成 DeepSeek 在线调用成功。
- 只在准备改变订单状态时点击 Accept 或 Confirm change；预览可以反复检查。
