# Week 5 / Week 6 文件变更日志

日期：2026-09-14。路径均相对于 `Workspace/`；依据执行前后文件 SHA-256 比对生成，未依赖上层 Git 仓库。

共新增 **49** 个文件、修改 **10** 个文件、删除 **0** 个文件。

已按用户指定完成 Google Gemini / gemini-2.5-flash / GEMINI_API_KEY 的官方 SDK 适配；增量见 [Gemini接入日志](CHANGELOG_GEMINI_CN.md)。

## 新增文件

| 文件 | 内容 / 目的 |
|---|---|
| `.env.example` | 新增环境变量说明；不含密钥，不自动加载。 |
| `.gitignore` | 忽略运行数据库、缓存和私密 .env。 |
| `README_parser.md` | 新增 Parser v1 字段、调用、状态、重试、telemetry、兼容迁移及在线评估说明。 |
| `app/agent/legacy_parser.py` | 保留原 Week 4 固定样例实现，供 fake_parse_request 显式兼容调用。 |
| `app/agent/llm_client.py` | 根据用户指定改为Google官方Gemini SDK；gemini-2.5-flash，仅读GEMINI_API_KEY。 |
| `app/agent/normalization.py` | 新增产品/工坊/数量词的可核对词典，不包含订单主数据。 |
| `app/agent/rule_parser.py` | 新增按语言模式提取的离线解析，不根据 R09 等标签猜字段。 |
| `app/agent/validator.py` | 新增 JSON/schema/业务/原文证据校验，阻止补造和漏掉已识别约束。 |
| `app/allocator/planner.py` | 新增确定性单工坊/整数拆单、最大工坊数、目标和硬交期筛选。 |
| `app/db/__init__.py` | 新增数据库包。 |
| `app/db/database.py` | 新增版本化 SQLite 建库、CSV 导入、连接与事务管理。 |
| `app/db/migrations/001_initial.sql` | 新增 orders/workshops/queue/request/parsing/working/unassigned/completed/lapsed/decision 表结构。 |
| `app/repositories/__init__.py` | 新增仓储包。 |
| `app/repositories/order_repository.py` | 新增真实订单精确检索及字段冲突检查。 |
| `app/repositories/workshop_repository.py` | 新增真实工坊和 current queue 检索，缺失/时间倒退阻断。 |
| `app/schemas/parser_schema.py` | 新增 ParseResult 与 JSON Schema v1，和 parsing_history 对齐。 |
| `app/server.py` | 新增本地 HTTP JSON API 和页面服务。 |
| `demos/day1_retrieval.py` | 新增 Day 1 真实检索 trace 演示。 |
| `demos/week5_mock.py` | 新增 5 条 Week 5 mock backend 链路演示。 |
| `demos/week6_demo.py` | 新增独立临时数据库的一键分配与幂等重放演示。 |
| `docs/CHANGELOG_GEMINI_CN.md` | Google Gemini适配增量日志；累计日志之外可单独核对本次修改。 |
| `docs/CHANGELOG_WEEK5_WEEK6_CN.md` | 本文件：逐项记录此次文件增删改及验证范围。 |
| `docs/DATABASE_SCHEMA_CN.md` | 新增 Schema2 计划字段映射、状态/幂等/队列/事务/迁移政策。 |
| `docs/NEXT_STAGE_CN.md` | 新增下一阶段优先级、责任建议、输入输出与验收标准。 |
| `docs/SYSTEM_GUIDE_CN.md` | 新增中文系统结构、运行、页面/CLI/API、人工操作、配置、排错与备份手册。 |
| `docs/WEEK5_WEEK6_ACCEPTANCE_CN.md` | 新增两份计划逐项交付对照，明确离线已完成与在线待验证。 |
| `docs/file_change_manifest.json` | 新增作业前后 SHA-256 对照，方便审计源文件是否改动。 |
| `docs/release_manifest.json` | 新增 Parser/Prompt/Pipeline/DB 本地版本冻结及 SHA-256。 |
| `evaluation/evaluate_dispatch.py` | 新增对原始 30 条请求的实际行为回归；不修改原标签。 |
| `evaluation/evaluate_parser.py` | 新增字段 exact/normalized、首轮有效率、补造率、模型日志评估。 |
| `evaluation/results/dispatch_behavior_metrics.json` | 保存原始 30 条请求的行为匹配结果。 |
| `evaluation/results/dispatch_runs.jsonl` | 保存 30 条真实数据独立运行结果与 trace。 |
| `evaluation/results/gemini_live_status.json` | 在线预检结果：缺GEMINI_API_KEY，未调用真实模型。 |
| `evaluation/results/parser_offline_metrics.json` | 保存本次 60 条 offline 解析指标，明确不是 LLM 成绩。 |
| `evaluation/results/parser_offline_runs.jsonl` | 保存每条 parser 输入/expected/raw/validated/telemetry/差异。 |
| `evaluation/results/test_results.txt` | 保存完整自动化测试报告。 |
| `evaluation/results/verification_summary.json` | 保存 Python 版本、验证时间、通过数和外部验收缺口。 |
| `evaluation/results/week5_mock_demo.jsonl` | 保存 5 条 Week 5 mock demo 原始输出。 |
| `evaluation/results/week6_demo.json` | 保存 Week 6 真实数据分配/队列变化/幂等重放和表行数。 |
| `evaluation/verify_gemini_live.py` | 新增在线单请求/60条完整验收脚本，明确区分NOT_RUN与通过。 |
| `evaluation/verify_mvp.py` | 新增一键测试、两周 demo、语言回归及官方 baseline 一致性验证。 |
| `requirements.txt` | 新增Google官方SDK固定版本依赖；离线核心仍无第三方依赖。 |
| `runtime/.gitkeep` | 预留运行数据库目录；本次验收不写入默认持久库。 |
| `tests/parser_golden.jsonl` | 新增 60 条显式完整 expected JSON，46 条 edge case。 |
| `tests/test_allocator.py` | 新增小规模整数穷举对照和硬交期容量测试。 |
| `tests/test_e2e.py` | 新增 20 个编号 E2E 主场景及异常补充测试，含并发、状态、SQL 故障回滚。 |
| `tests/test_gemini_sdk.py` | 新增10条真实SDK + 模拟HTTP专项测试。 |
| `tests/test_parser.py` | 新增 golden、schema、重试、补造和 LLM transport 替身测试。 |
| `tests/test_server.py` | 新增真实 HTTP 提交、历史、重放、参数和跨源检查。 |

## 修改文件

| 文件 | 修改说明 |
|---|---|
| `KNOWN_ISSUES.md` | 更新当前未完成/待确认项，移除已经实现的队列、DB、UI、拆单待办。 |
| `README.md` | 将 Week 4 骨架说明更新为 Week 5/6 入口、运行命令和验收边界。 |
| `app/agent/parser.py` | 替换按 R 编号返回固定内容的主解析器，接入 offline/llm、校验及一次重试。 |
| `app/agent/prompts.py` | 冻结 Prompt v1、few-shot、字段/否定/日期/业务隔离规则。 |
| `app/cli.py` | 增加自由消息、数据库、backend、业务日期和幂等 key 参数；保留 R 标签入口。 |
| `app/pipeline.py` | 改为真实数据库主流程，增加事务、状态保护、幂等及可追踪返回值。 |
| `app/ui/index.html` | 将静态 R09 mock 更新为可提交/展示/查看历史与审计的实际页面。 |
| `docs/schema_contracts.md` | 保留 Week 4 契约，追加新旧版本迁移说明。 |
| `tests/test_golden_cases.py` | 只显式固定 offline backend，保留原 Week 4 断言，避免环境变量意外触发外部模型。 |
| `tests/test_tools.py` | 只显式固定 offline backend，保留原工具测试断言。 |

## 删除文件

无。旧固定样例解析实现复制保存在 `app/agent/legacy_parser.py`，原入口改为新解析器，并非丢弃旧成果。

## 保留未改动内容

- Plans 下三份计划 PDF、track2 原始材料，以及 Workspace/data 原始 CSV/字典/消息。
- 官方 harness/simulate.py、Week 4 baseline_results.txt、language_ground_truth.csv、历史 fixtures、r09_demo.json 和其余旧 schema/tools/allocator。
- 本次测试/浏览器演示使用内存库或 /tmp 独立数据库；没有重置既有持久化业务库。

## 自动生成与环境说明

Python 执行/编译会生成或更新 `__pycache__/*.pyc`；此类可再生缓存以及系统 .DS_Store 不纳入上述源文件清单，已由 .gitignore 排除。runtime 运行库在用户启动时自动创建，也不作为源文件交付。

读取计划时，通过已批准的 uv 命令下载了 pypdf/pymupdf 到 uv 开发缓存；这些不是应用依赖；另在Workspace/.venv安装了Gemini在线模式所需的Google官方SDK（由requirements.txt固定），该可再生环境已忽略，不计入上面的源文件数。PDF 提取、截图和临时开发脚本放在 /tmp，没有修改计划原件。

## 验证与尚待事项

当前完整测试、offline golden、30 条行为回归和模拟器一致性结果见 `evaluation/results/verification_summary.json`；页面已实际提交验证。Google Gemini模型已固定，真实在线验收尚待GEMINI_API_KEY；Data Schema2 原始定义和第二位人工标注复核尚待完成。

机器可读 before/after SHA-256 见 `file_change_manifest.json`；该清单不对自身递归计算 hash。
