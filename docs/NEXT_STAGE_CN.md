# 下一阶段交接说明

更新：2026-10-02。GitHub 分支：`ningtao`；当前版本 **MVP v0.2 / Parser、Prompt v1 / Database v2**。先阅读 [本轮变更](CHANGELOG_LIFECYCLE_CN.md) 和 [生命周期手册](LIFECYCLE_CN.md)，再按下列顺序继续。

## 本轮已经完成，不必重复实现

1. 真实 Gemini 冒烟成功；首次完整 60 条在线回归已执行并留下证据，但因 46 条 HTTP 429 **未通过完整验收**。已补服务错误分类和评估用例间隔参数。
2. 原交接“第二优先级第 1 项”完成：complete/cancel/lapse/reassign、部分完工、操作人/原因、版本检查、幂等、事务回滚及审计。
3. 已提供页面、HTTP、CLI 和在同一个持久化临时数据库上的生命周期连续演示。已验证旧 v1 库事务升级、队列不重置及迁移失败回滚。
4. 当前 **150 条测试通过、0 跳过**；60 条离线解析、30 条行为标签、官方 standard/shock 基线均通过。Chrome 实际完成部分完工、重派和整单完工。

完整验收入口：`evaluation/verify_mvp.py`；最新摘要：`evaluation/results/verification_summary.json`。`docs/release_manifest.json` 是当前冻结版本；`docs/file_change_manifest.json` 是 2026-09-14 历史清单，勿把它当作 v0.2 文件状态。

## 第一优先级：补齐在线与外部验收

| 工作 | 输入 / 前提 | 下一步操作 | 完成条件 |
|---|---|---|---|
| Gemini 服务可用性与完整回归 | 已指定 gemini-3.5-flash / GEMINI_API_KEY，项目实际配额 | 先查 429 的配额原因；恢复后先冒烟，再按配额运行带间隔的 --full；保留本轮失败基线 | 首轮有效率 ≥98%、核心字段 ≥90%、观测补造为零；全部 60 条计入分母 |
| 模型运行限速与退避 | 当前错误统计：91 次429、6 次503（覆盖重试） | 在不增加无限重试的前提下，增加有界退避/必要的全局限速和请求追踪；区分连接失败、配额不足和校验失败 | 模拟时钟覆盖退避、并发限速、超时；真实流量确认有效；任何失败仍不分配 |
| Data Schema2 原件比对 | 原始 ERD/DDL，仓库中仍未提供 | 比对 DATABASE_SCHEMA_CN.md 和 migrations 001/002；记录每个差异 | 有逐列核对记录；变更通过新增 003 迁移，已发布迁移不重写 |
| 标注复核与 holdout | 第二位团队成员；60 条 JSON 和原始30条标签 | 记录 reviewer、日期、分歧和依据；另建未参与调试的表达集 | 有人工复核记录和独立结果，不根据当前程序输出来改 expected |
| 业务政策确认 | 团队/业务负责人 | 确认 cancel=撤销分配返READY、lapse=终止、部分完工保留、重派约束全部重新填写、日历天FIFO、软/硬交期 | 留下书面确认；如调整政策，同时更新接口、迁移、测试和文档 |

完整在线命令示例（10 秒不是服务商承诺的配额值，须按实际项目调整）：

```bash
source .venv/bin/activate
python evaluation/verify_gemini_live.py
python evaluation/verify_gemini_live.py --full --interval-seconds 10 \
  --output-dir evaluation/live_results/next-run
```

等待间隔只在评估用例之间生效；现有 Parser 的一次重试仍没有退避。HTTP 429 不能单凭代码判断是分钟额度、每日额度还是服务容量；不要反复无间隔运行全量。在线输出在忽略目录中，审核后的无密钥摘要再单独提交。

## 第二优先级：下一个主要功能是 Session / 多轮澄清

生命周期闭环已完成，下一次开发可直接从此项开始；无需等标注或 ERD 才做独立设计和测试，但不要伪造外部确认。

建议依次交付：

1. **冻结会话契约。** 明确 session_id、每条消息独立 request_id、message sequence、role、当前确认字段和待澄清字段；区分 ACTIVE / AWAITING_CLARIFICATION / CLOSED 等状态及迁移规则。
2. **新增迁移。** 添加 sessions/messages，业务写入仍走现有分配/生命周期事务；序列和会话版本要支持并发冲突检查。若第一优先级已经使用了 003，顺延迁移编号。
3. **显式合并约束。** 从“澄清问题 → 回复 → 更新已确认字段”状态机开始。测试“改成两个工坊”“不要 W3”“取消刚才的排除”等覆盖旧约束；不能仅拼接历史文本后把冲突交给下游猜。
4. **隔离与幂等。** 同一条回复重放不重复分配；跨 session 不串订单；两个客户端同时回复时至多一个版本生效。订单已被其他请求分配/完成时必须沿用当前状态和版本保护。
5. **接入页面/API/CLI。** 页面明确当前会话、待回答问题与结束/新建入口；旧单消息调用保持兼容。再决定何时启用 Parser context_messages，不直接改变冻结 v1 的非空上下文报错语义。
6. **验收和提交。** 新增真实多轮 E2E、并发/中断恢复、覆盖旧约束、跨会话和部分完工订单测试；跑完整验收；更新 release manifest、中文使用说明及此交接文件，按功能分英文 commit 推送 ningtao。

完成标准：同一持久库上演示“缺失订单号 → 回答 → 修改约束 → 分配”，同时证明跨会话隔离、重复回复幂等，原有完工/撤销/重派及 150 条基线不退化。

## 第三优先级：数据管理与课程评估

- **真实数据同步与管理入口**：CSV 目前是初始化种子；先明确后续是事件还是外部快照。增加工坊关闭/恢复、产能变更、队列校正；必须有版本检查和审计，并维护 baseline + 活动预留 = current_queue_days，不能只直接 UPDATE 聚合队列。
- **官方 simulator adapter**：新增调用 `Simulator.run(allocator, name)` 的适配，保持 `harness/simulate.py` 原样；官方接口只返回一个 workshop_id，拆单另做补充实验。
- **对比实验**：随机、最大产能、最低成本和新策略，固定 seed，覆盖 standard/shock，记录 mean/P90 turnaround、late、defect、cost、max share。当前一致性回归不代表新算法优于基线。
- **算法/解析迭代**：hybrid 仍为启发式；先明确权重/单位/约束再考虑 DP/MILP。复杂否定、预算、精确拆单、更多中文、多个日期和千位分隔符另建错误集，优先避免错误分配。
- **时间政策**：确认周日停工、运输、返工和插单定义，再改时间模型。当前日历天/ceil 显示和官方 round 仍需在报告中区分。

RAG、Agent 编排、公网部署、账号权限、备份自动化继续留在明确需求之后，不阻塞当前课程主链路。

## 下次接手最短检查清单

```bash
git status --short --branch
git pull --ff-only origin ningtao
source .venv/bin/activate
python evaluation/verify_mvp.py
python -m demos.lifecycle_demo
python -m app.server --db runtime/session-development.sqlite3
```

已有 runtime 库先停服务并备份；新功能开发优先使用单独数据库。不要清空 working_order 来“撤销”，不要重置已完工数，不要提交密钥或运行库。Parser/schema 语义变动必须同步 Prompt、校验器、迁移、golden 及接口说明；仅文档变化不需要无意义地重跑全套模型请求。
