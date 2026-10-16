# Week 5 / Week 6 计划逐项验收

> 本文主体是 2026-09-14 历史记录；2026-10-02 当前状态见文末更新节及 [本轮变更](CHANGELOG_LIFECYCLE_CN.md)。

依据：`Plans/Week5_Execution_Plan.pdf`（8 页）及 `Plans/Week6_Execution_Plan.pdf`（10 页）；继承 Week 4 真实 CSV、30 条语言标签和官方 simulator。实现位于 `Workspace`。两份计划原文件和原始数据均未修改。

结论：**本地代码交付和离线集成验收完成；真实 LLM 在线验收及 Data Schema2 原定义核对尚待外部信息。** 用户已确认 Google Gemini / gemini-3.5-flash / GEMINI_API_KEY，官方 SDK 适配和11条专项测试已完成；当前仅缺密钥和真实在线验收。

## Week 5

| 计划项 | 交付物 / 证据 | 状态 |
|---|---|---|
| Day 1 固定输入输出、类型、null、状态、objective/exclusion | parser_schema.py、README_parser.md；exclusion 为 W ID 数组 | 已实现 |
| 与 Schema2 parsing_history 一一映射 | migration 001、DATABASE_SCHEMA_CN.md | 已按计划字段映射；原 Schema2 待核对 |
| stateless，预留 context_messages | parse_request(message, context_messages=[])；非空明确停止 | 已验证 |
| Day 2 Prompt v1 + structured output | prompts.py + llm_client.py，严格 JSON Schema | 接口/请求结构已测试；Gemini SDK 模拟网络测试通过；真实模型待配置密钥验证 |
| Day 3 40–60 Golden Set，≥30% edge | tests/parser_golden.jsonl：60 条，46 条 edge，完整 expected JSON | 离线 60/60；人工第二次复核待完成 |
| 字段 exact/normalized、补造率、raw/validated telemetry | evaluate_parser.py、parser_offline_metrics.json、parser_offline_runs.jsonl | 已实现并运行；不能替代在线模型评估 |
| Day 4 结构与业务校验、一次 retry、非法结果不下游 | validator.py、parser.py、tests/test_parser.py | 已验证，包括无凭据/临时错误/错误 JSON/额外字段/补造 |
| Day 5 mock backend，至少 5 个 demo | demos/week5_mock.py + week5_mock_demo.jsonl | 5 条可重复案例，正常/缺失/非法/否定/冲突 |
| parser/prompt v1 freeze | docs/release_manifest.json；schema 与字段说明固定 | 本地冻结；已按指定 Gemini 更新 transport；Parser/Prompt/DB 语义保持 v1 |
| validity≥98%、核心≥90%、补造≈0 | 当前离线：100%、100%、0/549 缺失槽 | 离线达标；**真实 LLM 尚未测量** |

## Week 6

| 计划项 | 交付物 / 证据 | 状态 |
|---|---|---|
| Day 1 parsing log + 真实订单/工坊仓储 | DB migration、order_repository.py、workshop_repository.py | 导入 120 订单/8 工坊；精确 ID 检索 |
| order 不存在/冲突/DB error 统一阻断 | tests/test_e2e.py | 已验证，R18 保留 DECLINE，无猜测 |
| Day 2 确定性 eligibility + current queue | planner.py + workshop_repository.py | 状态/类别/cap/排除/队列缺失/日期倒退都有代码原因 |
| Day 3 单工坊/多工坊 + 数量守恒 + 最大工坊数 | planner.py + tests/test_allocator.py | 整数拆单；3 个主要目标用小规模穷举对照 |
| success → working_order/decision_log/queue/state | pipeline.py，week6_demo.json | 已验证，完整事务提交 |
| 无可行方案 → unassigned_order | NO_ELIGIBLE_WORKSHOP、CAPACITY_INFEASIBLE、DEADLINE_INFEASIBLE | 已验证，新 key 可重试 |
| 系统错误不半更新、可回滚 | 测试注入 SQL trigger 中途报错 | 工作记录、状态、队列一起回滚；错误另行审计 |
| Day 4 10–20 类 E2E 和异常 | 20 个编号主场景 + 队列/数据库补充场景 | 已通过，覆盖并发幂等、重复分配、已完成/失效状态 |
| Day 5 一键 clean demo、可重复、trace 全链路 | demos/week6_demo.py，verification_summary.json | 已验证；独立临时库，不删 runtime |
| 状态语义与人工步骤 | DATABASE_SCHEMA_CN.md、SYSTEM_GUIDE_CN.md | 实现政策已明确；业务方确认待完成 |
| 端到端真实 LLM 模式 | CLI/server/demo 均可选择 --backend llm | 官方 Gemini SDK 已适配；在线请求待 GEMINI_API_KEY |
| UI 集成（延续 Week 4） | server.py + ui/index.html | 真实 Chrome 提交并检查 ALLOCATE、候选表和历史记录 |

## 自动化证据

运行：`python3 evaluation/verify_mvp.py`，在已安装 requirements.txt 的 .venv 内运行，输出至 `evaluation/results/`。

- **117 条自动测试全部通过（0跳过）**：包括原有 8 条 Week 4 测试、60 条解析 golden、12 条解析/transport 校验、22 条 E2E、2 条分配验证、2 条 HTTP 接口测试，以及新增11条真实 Google SDK / 模拟 HTTP 专项测试。
- Parser 60/60 完整字段匹配；核心字段和 normalized match 100%；missing-field hallucination 0/549。此数字只描述本仓库离线回归集。
- 原始 30 条 dispatch 请求与 Week 4 行为标签 **30/30 匹配**；每条用独立数据库，只评估行为，不把它当作 30 条连续生产分配测试。
- 标准 / shock 官方 simulator 与原 baseline_results.txt 完全一致。该结果证明基线未破坏，不证明新策略优于 baseline。
- Week 6 干净库 demo 成功，重复 key 重放 true；请求、解析、工作分配和决策各 1 行。
- 页面检查：在本机 Chrome 通过页面按钮提交 ORD-045，实际显示 Nimble Needle / 150 件 / 180.00 / 3.15 天，候选理由与历史记录可见。

真实 Gemini 在线状态单独记录于 `evaluation/results/gemini_live_status.json`；此次 NOT_RUN，原因 gemini_api_key_missing。

## 本版主动界定的业务规则

为了让系统当前即可运行，采用并记录以下规则：订单 ID 精确匹配；最大工坊数默认 1；指定工坊要求其接整单；逾期不自动 lapsed；明确 on-time 才启用硬交期；不自动改订单主数据；队列缺失报错；日期按日历天；系统展示交付日期保守取 ceil。它们是实现选择，不能冒充原 Data Schema2 已确认的规则。

下一阶段的验收缺口和推进顺序见 [NEXT_STAGE_CN.md](NEXT_STAGE_CN.md)。

## 后续验收更新（2026-10-02，MVP v0.2）

上文保留 2026-09-14 的 Week 5/6 历史验收结论；当前状态以本节及最新 verification_summary.json 为准。

- 真实 Gemini 冒烟已成功，不再是缺密钥 NOT_RUN；60 条完整回归中 14 条匹配、46 条 HTTP 429，完整验收仍不通过。见 [在线记录](GEMINI_LIVE_ACCEPTANCE_CN.md)。
- 新增生产生命周期、migration 002、操作审计、页面/API/CLI，验收覆盖部分完工、撤销、重派、失效、队列与并发/回滚。
- 当前 150 条自动测试全部通过（0跳过）；60 条离线解析、30 条行为回归和官方基线一致性保持通过。
- Chrome 实际操作及生命周期连续持久库演示已验证；Data Schema2 原件核对、第二人标注复核和独立 holdout 仍待完成。
- 下一步主要功能推进到 Session / 多轮澄清；执行清单见 [下一阶段交接](NEXT_STAGE_CN.md)。

## 后续进展（2026-10-03，MVP v0.3）

会话持久化、显式约束修改、预览/确认与页面/API/CLI已完成；官方模拟器单工坊适配及14组四目标/三基线比较已完成。当前168条测试通过、0跳过。上述Week5/6历史数据保留，最新范围和证据见 [Week8/9验收](WEEK8_WEEK9_ACCEPTANCE_CN.md)；真实Gemini全量验收缺口仍未关闭。
