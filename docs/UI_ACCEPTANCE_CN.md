# MVP v0.4 UI 需求对照与验收记录

更新：2026-10-06。原件：`UI_requirement/Track2_UI_Requirements.docx`、`UI_requirement/UX design.pptx`。仓库中的逐字原件副本见 [requirements](requirements/README.md)。用户已确认新页面采用英文。

## 功能需求映射

| 原需求 | 实现及入口 | 验证证据 |
|---|---|---|
| FR-01 Request Intake | New request 自然语言输入、默认目标、持久化草稿 | HTTP 和浏览器缺订单号输入 |
| FR-02 Clarification Handling | 阻断不完整请求、补充订单号、单项修改、完整替换 | HTTP 澄清、拒绝、修订、确认；Safari 澄清及刷新 |
| FR-03 Workshop Eligibility Check | 状态、产品能力、用户排除、批量上限，展示不合格原因 | 原分配器测试和 UI 资格展示；W7 suspended 不分配 |
| FR-04 Delivery Date Estimation | 队列 + 生产 + 取件，多工坊使用最长时间，整日 ETA | 原分配器/交付测试；Safari 查看候选 ETA |
| FR-05 Recommendation Engine | 最快、最低成本、最低缺陷、时间质量混合目标 | 原算法及 14 组模拟器回归；UI 切换入口 |
| FR-06 Explainable Allocation | Decision review 提供每部分数量、天数组成、成本、原因码及排除项 | Safari ORD-045 / FreshStart 理由页；审计记录保存实际数值 |
| FR-07 Decision Audit Log | 全量历史、筛选、分页、原文、解析、审批人/时间、CSV/JSON | 33 条记录跨页导出测试、事务失败回滚、审批人伪造拦截 |
| FR-08 Workshop Explorer | 工坊查询、状态和类别筛选、容量/批量/队列/订单详情 | Active + Accessories、Suspended、名称查询及不改业务数据测试 |

PowerPoint 中的五个页面分别落在 Sign in、Overview、Recommendations、Decision review、Allocation history。原草图的页码跳转标注有重复，本次按页面名称实现。新增 Workshop explorer 和 Production 为工坊需求与旧生命周期功能提供明确入口。

Accept 后留在 Recommendations，理由页接受也返回 Recommendations；Reject 先保存拒绝再打开同一会话的修订窗口，以保留完整审计链。开放请求和未分配订单均为空时显示“All orders are assigned”。

## 自动验证

2026-10-05 保存的完整回归结果：

- Python：181 条测试，0 失败、0 错误、0 跳过；其中本次新增 13 条 `test_desk.py`。
- Parser：60/60 离线 golden；原始请求行为：30/30。
- 生命周期、会话、幂等重放、队列守恒及模拟器基线保持通过。
- 14 组模拟器运行完成，未修改算法目标、原数据或官方基线。
- 2026-10-06 增补前端控制器测试 5 条，覆盖确认条件、失败后持久化重试、创建后首轮重试、版本冲突和快速重复确认。它们使用 Node 最小 DOM stub，不是浏览器自动化或布局测试。

可复现命令：

```bash
.venv/bin/python evaluation/verify_mvp.py
node --test tests/test_ui_state.cjs
node --check app/ui/desk.js
.venv/bin/python evaluation/verify_ui.py
```

后两种 JavaScript 检查需要 Node 18+；运行应用本身无需 Node 或 npm。证据：[完整结果](../evaluation/results/verification_summary.json)、[Python 测试明细](../evaluation/results/test_results.txt)、[前端测试明细](../evaluation/results/ui_controller_tests.txt)、[延迟数据](../evaluation/results/ui_latency.json)。

## 非功能需求与测量范围

| 需求 | 结果及边界 |
|---|---|
| Response time under 3 seconds | 本机、离线、已认证 HTTP 的全部观测样本满足。预览 20 次，p95 4.65ms / max 6.82ms；确认 10 次，max 3.99ms；登录单样本 72.81ms。不是浏览器绘制、并发负载或 Gemini 延迟保证 |
| Explainable recommendations | 展示实际计算字段、候选和排除原因，保留混合目标为启发式的说明。尚不能代替原课程 30 条解释忠实性的独立人工评分 |
| Avoid ineligible allocations | 复用确定性资格校验，前端和服务端均阻止不完整确认，已有资格/整数件数/批量测试保持通过 |
| Ease of use under time pressure | 增加队列检索、明确状态、错误反馈和统一导航。尚未进行独立用户计时研究 |
| Full auditability | UI 的操作身份、输入、回合、决定和批准时间均持久化，审批和业务写入同事务。旧记录及无 actor 的 CLI 不补造身份；没有防管理员篡改的外部审计存储 |
| Mobile responsive UI | 已实现 1150px 和 800px 响应式规则、单列内容与表格局部滚动。移动设备/手机宽度实机检查尚未完成，不能标记为全设备验收通过 |

性能脚本使用 120 个导入订单、8 个工坊的独立临时库；20 次预览、10 次确认、30 条导出记录。相关数据库在脚本退出时销毁，不触碰用户 runtime。

## 实际浏览器检查

2026-10-05 在 Safari、本机 8014 端口、独立临时数据库完成：

1. 使用临时测试账号登录，首页显示 34 个初始待办、真实工坊队列。
2. 新建缺订单号请求，出现 Needs clarification，Accept 不可用。
3. 刷新后恢复同一会话及原始请求。
4. 补充 ORD-045 后生成 FreshStart 推荐，150 件、成本 150 单位、预计 2026-04-05 完成。
5. 理由页展示最小成本目标、0 + 1.5 + 2 = 3.5 天、工坊排除原因。
6. Reject & revise 记录拒绝并显示修订窗口。
7. 检查桌面页面与弹窗截图，修正解析字段区域被嵌套网格挤窄的问题，并加入路由切换回到页首和修订窗口输入聚焦。

后续浏览器控制曾受到窗口切换影响；2026-10-06 恢复时 Safari、Chrome 均返回 `cgWindowNotFound`，窗口枚举超时。未将尚未可靠完成的浏览器操作列为通过。完整的“修订 → 接受 → 审批人 → 历史 → 导出”已由 HTTP 测试覆盖，但最终浏览器点击链、移动布局和生产页实机仍需在可用浏览器环境补验。

## 未变更的验收边界

本轮没有真实 Gemini 请求，在线全量验收仍沿用 2026-10-02 的失败结论；离线通过不能代替在线通过。Schema2 原件、独立 holdout、标签人工复核、解释忠实性评分、角色授权、工坊状态/产能编辑仍未完成。详情见 [已知限制](../KNOWN_ISSUES.md)。
