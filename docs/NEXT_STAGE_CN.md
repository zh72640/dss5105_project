# 下一阶段交接说明

交接起点：Week 5 Parser v1 + Week 6 MVP v0.1 已在离线模式完成实现和集成验证。先阅读 [系统说明](SYSTEM_GUIDE_CN.md)，运行 `python3 evaluation/verify_mvp.py`，确认本地环境与当前交付一致。冻结文件见 `release_manifest.json`，不要在未记录版本变化时直接改字段语义。

## 第一优先级：完成外部核对与在线验收

用户在2.5出现404后，已确认改用 Google Gemini、gemini-3.5-flash、官方默认 API 地址、GEMINI_API_KEY；无需再次询问服务商。已完成代码适配，下一步在设置密钥的终端运行 `python evaluation/verify_gemini_live.py --full`。

| 工作 | 建议责任人 | 输入 | 产出 / 验收 |
|---|---|---|---|
| 配置已指定 Gemini 的密钥并验收 | 使用者 + M1 | Google 官方 gemini-3.5-flash；仅设置 GEMINI_API_KEY，不把密钥写进仓库 | 一条真实 LLM 请求成功，raw/validated telemetry 可查 |
| 跑真实模型回归 | M1 + 测试成员 | 人工复核过的 60 条 golden set | 首轮结构有效率 ≥98%、核心字段准确率 ≥90%、补造率尽可能为0；保留错误样例 |
| 核对 Data Schema2 原文件 | 后端成员 + M1 | 原始 ERD/DDL | 和 DATABASE_SCHEMA_CN.md 逐列比对；需变更则新增 migration 002 |
| 复核标注 | 第二位团队成员 | 60 条完整 JSON + 30 条原始行为标签 | 记录 reviewer/日期/分歧及处理依据；不要只根据程序输出修改 expected |
| 确认状态和时间政策 | 全队/业务负责人 | 逾期订单、默认单工坊、指定工坊、交期规则 | 明确确认记录；特别区分 overdue 与 lapsed |

真实模型尚未验证是本轮验收的明确缺口，不应在课程报告中写成“LLM 100%”。离线集与实现共同形成，下一阶段应另建未参与调试的 holdout 测试集。

## 第二优先级：把演示系统补成可持续操作的系统

1. **生产生命周期与人工撤销。** 增加受控的 complete/lapse/cancel/reassign 操作、操作人和审计。撤销必须一致更新 working_order、orders.state、queue、decision_log；不能只删记录。测试重复事件、部分完工、撤销后重派及事务回滚。
2. **Session / 多轮澄清。** 新增 sessions/messages（role/content/sequence），继续保留每条消息 request_id。将“澄清问题 → 用户回复 → 合并已确认字段”作为显式状态机，之后再启用 context_messages。要求用户改口能覆盖旧约束、跨会话不串单。
3. **真实数据同步与管理入口。** 明确 CSV 是导入种子还是外部系统快照，增加工坊关闭/恢复、产能变更、队列校正；并发更新需版本检查和操作审计。
4. **稳健的模型运行配置。** Google 官方 adapter 已完成，模型固定 gemini-3.5-flash；接下来按真实流量评估限速、退避和请求追踪。审计原文与 raw output 的保留时长、访问权限应由团队确定。

此阶段完成标准：在同一持久化数据库上连续演示“分配 → 完工/撤销 → 再分配”，所有数量、状态与队列仍能一致核对。

## 第三优先级：课程评估与算法迭代

- 给新 allocator 增加官方 `Simulator.run(allocator, name)` adapter，保持 `harness/simulate.py` 原样。官方接口仅返回单个 workshop_id；拆单算法需要另建补充评估，不应悄改官方评分接口。
- 对比随机、最大产能、最低成本与新策略，记录 mean/P90 turnaround、late、defect、cost、max share，覆盖 standard/shock 和明确随机种子。
- 当前 hybrid 只是对候选速度拆单的启发式评分；如需要最优混合目标，定义权重、单位和约束后再引入 DP/MILP 等方法，验证收益与运行成本。
- 对当前未支持表达建立错误集，例如复杂否定、金额预算、精确拆单、更多中文、多个日期、数量千位分隔符。优先降低错误分配，其次增加覆盖率。
- 确認工厂周日停工、transport 是否独占队列、返工和紧急插单的业务定义，再调整时间计算。当前日历天与保守 ceil 展示必须在评估时注明。

## 可选增强，勿抢先阻塞主链路

RAG 只在引入非结构化工坊资料/规章后评估；Agent 编排只在固定流程不够时评估；自然语言 verbalizer 只能解释已有 structured decision，不能重选工坊。公网部署、身份权限、多人操作和数据备份策略应在确定演示以外的使用需求后单独设计。

## 下次接手时的最短检查清单

```bash
cd Workspace
python3 evaluation/verify_mvp.py
python3 -m demos.week6_demo
python3 -m app.server
```

打开 `docs/WEEK5_WEEK6_ACCEPTANCE_CN.md` 与 `evaluation/results/verification_summary.json` 核对状态，读取 `KNOWN_ISSUES.md`，再选择上面一个有明确验收条件的任务开始。任何 schema 语义变动要一起更新 Prompt、校验器、数据库迁移、golden expectations、接口文档和 release manifest。
