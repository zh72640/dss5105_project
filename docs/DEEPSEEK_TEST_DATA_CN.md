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

## 完成首轮后的扩展测试

再次只读核对时：服务健康接口为 `backend=deepseek`；ORD-063 已分配 W6，100 件，累计完工 0；ORD-109（500 件）与 ORD-015（300 件）仍为 READY。以下操作以此状态为起点。所有数量和方案预期来自业务规则及本地只读计算，尚未代替用户执行这些生产变更。

### 1. 实际拆单与摘要完整性

New request：

```text
Allocate ORD-109 at the lowest cost; exclude W3; use at most two workshops.
```

当前预期为 W8 / FreshStart 300 件、W5 / GiantWeave 200 件，总计 500 件，总成本 520 cost units，ETA 2026-04-09。核对自然语言摘要是否列出两个工坊，明细总数是否守恒。最多两个工坊通常不保证一定拆成两份；本例因为 W8 单价较低且上限为 300，拆分才降低总成本。确认后到 Production 对照两条实际分配；其他审批改变队列时，日期可能变化。

### 2. 多轮修改是否保留旧约束

另开请求，先不要审批：

```text
Allocate ORD-015 at the lowest cost; exclude W3 and W7; use at most two workshops.
```

接着发送：

```text
Please prioritize the lowest defect rate and exclude W5 as well.
```

预期保持 ORD-015 和最多两个工坊，目标改为 Lowest defects，排除集合为 W3、W5、W7。再发送 `unexclude W3`，应只移除 W3，仍排除 W5、W7；发送 `clear exclusions` 才清空全部排除。每次修改只更新草稿，不能自动变为已审批。

### 3. 生产闭环与失败保护

Production 加载 ORD-063，按顺序操作；每次操作填写 Reason，例如 `Course demo: partial completion`，先 Review 再 Confirm。记录完成数填写本次新增数量。

| 步骤 | 操作和数据 | 预期 |
|---|---|---|
| 1 | Record completion，W6，40 件 | 累计完成 40，剩余 60，仍在生产 |
| 2 | 再尝试 Record completion，W6，61 件 | 拒绝超额完工；累计仍为 40，剩余仍为 60 |
| 3 | Reassign remaining pieces，Preferred ID 填 W7，其余保持默认 | W7 已停用，重派失败；原 W6 的 60 件分配保留 |
| 4 | 重新读取订单，Reassign remaining pieces，Preferred ID 填 W8 | W8 接收剩余 60 件，累计完成仍为 40；不会重派已经完成的 40 件 |
| 5 | Record completion，W8，60 件 | 累计 100，剩余 0，订单变为 Completed |

重派是完整的新约束提交，不会自动继承原始分配请求的排除或目标；有必要保留的约束应在重派表单再次填写。步骤 5 完成后该订单不能再次用于首次分配测试。

### 4. 防止重复分配

在另一个 New request 输入 `Allocate ORD-063 at the lowest cost.`。无论它此时还是 WORKING，还是已经 COMPLETED，都应拒绝再次分配。Production 数量与工坊队列不应因此增加。

### 5. 两个窗口的旧版本保护

使用第 2 项尚未审批的 ORD-015 会话。在浏览器中复制标签页，确认两个页面显示同一请求和同一修订版本。在 B 页发送 `exclude W6` 并等更新成功；回到尚未刷新的 A 页点击 Accept allocation。

预期 A 页收到版本冲突或要求重新加载，不会批准旧方案。重新打开该请求，确认 W6 排除存在，再决定是否审批。测试时不要在修改 B 页后提前刷新 A 页，否则无法触发旧版本保护。

### 6. 历史与导出对账

Allocation history 查 ORD-063：应能看到初次分配、40 件完工、失败重派、成功重派和最终完工；失败操作不应被标为成功审批。查 ORD-109 时，明细应包含 W8 / 300 与 W5 / 200。

导出 CSV / JSON，核对订单、操作者、原因、分配数量、状态和时间。导出包含所有页面和筛选外记录，不能把它当成当前筛选结果。首页摘要保留当时的分配决策，完成或重派后的最新状态以 Production 为准。
