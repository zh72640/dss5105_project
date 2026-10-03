# SweaterCo Dispatch Desk — MVP v0.3

自然语言分配 → Parser v1 → SQLite 检索 → 工坊资格/队列 → 单工坊或整数拆单 → 事务写库 → 页面/JSON 结果。本版进一步支持**部分/全部完工、撤销分配、失效、重派**，保留已完工件数，配合版本检查、幂等和操作审计。

2026-10-03 新增**持久化多轮澄清、修改约束、预览及显式确认分配**，支持刷新恢复、页面/API/CLI 和并发版本保护。新增官方模拟器适配，对四种目标和三种基线运行 standard/shock，共 14 组实验。Week 8 为本项目内部推进阶段；Week 9 对齐课程 Sprint 1 展示。

默认使用**离线规则解析**，无需第三方 Python 包。真实 LLM 使用 **Google 官方 `google-genai` SDK / `gemini-3.5-flash`**，仅从 `GEMINI_API_KEY` 读取密钥。2026-10-02 真实请求已成功，完整 60 条评估因 46 条 HTTP 429 未达验收标准；详情见[在线验收记录](docs/GEMINI_LIVE_ACCEPTANCE_CN.md)。

## 立即运行

在项目目录执行（Python 3.10+；验证环境为 3.14.3）：

```bash
# 同一临时持久库演示分配、部分完工、撤销、重新分配、重派和完工
python3 -m demos.lifecycle_demo

# 缺订单号 → 补充 → 修改约束 → 确认 → 幂等重放
python3 -m demos.session_demo

# 启动页面
python3 -m app.server
```

浏览器打开 <http://127.0.0.1:8000>。首次启动从 CSV 初始化 `runtime/dispatch.sqlite3`，以后保留状态。旧 v1/v2 库自动事务升级到 migration 003；请先停服务备份旧库，步骤见 [部署说明](docs/DEPLOYMENT_CN.md)。演示脚本使用独立临时库，不重置 runtime。

页面新增“生产进度与分配调整”：读取订单 → 核对状态/数量 → 填操作人和原因 → 选择操作并保存。cancel 表示撤销当前分配、允许再次分配；lapse 才是终止订单。详见[生命周期手册](docs/LIFECYCLE_CN.md)。

```bash
# 隔离分配请求
python3 -m app.cli --request R09 --db :memory:

# 查询持久库中的订单、版本及活动分配
python3 -m app.lifecycle_cli inspect ORD-045

# 一键完整验收，生成 evaluation/results/ 下的报告
.venv/bin/python evaluation/verify_mvp.py
```

## 文档入口

- [整体项目说明](docs/PROJECT_OVERVIEW_CN.md)、[最新部署说明](docs/DEPLOYMENT_CN.md)。
- [本轮修改说明](docs/CHANGELOG_WEEK8_WEEK9_CN.md)、[Week 8/9 验收](docs/WEEK8_WEEK9_ACCEPTANCE_CN.md)、[Week 9 演示讲稿](docs/SPRINT1_REVIEW_CN.md)。
- [多轮会话说明](docs/SESSIONS_CN.md)、[模拟器对比结果](evaluation/results/simulator_comparison_CN.md)。
- [系统说明与手动操作](docs/SYSTEM_GUIDE_CN.md)：环境、页面、CLI/API、模型和排错。
- [生命周期规则与接口](docs/LIFECYCLE_CN.md)：数量、队列、迁移、状态、审计及操作示例。
- [v0.2 历史变更与验收](docs/CHANGELOG_LIFECYCLE_CN.md)：生命周期交付记录。
- [下一阶段交接](docs/NEXT_STAGE_CN.md)：已完成项、后续顺序、输入与验收条件。
- [Gemini 在线验收](docs/GEMINI_LIVE_ACCEPTANCE_CN.md)：首次真实评估及限流问题。
- [Parser v1](README_parser.md)、[数据库说明](docs/DATABASE_SCHEMA_CN.md)、[已知限制](KNOWN_ISSUES.md)。
- [Week 5/6 验收记录](docs/WEEK5_WEEK6_ACCEPTANCE_CN.md)、[历史变更日志](docs/CHANGELOG_WEEK5_WEEK6_CN.md)。

## 使用 Google Gemini

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 在当前终端安全设置 GEMINI_API_KEY，操作方式见系统说明
python -m app.server --backend llm
```

模型和官方地址已固定。`python evaluation/verify_gemini_live.py` 做真实冒烟；按项目配额恢复情况选择 `--full --interval-seconds 10` 做完整评估。等待间隔只控制用例之间的速度，不保证消除配额不足。原始在线输出保存在已忽略的 `evaluation/live_results/`。

## 已验证结果

**168 条自动测试全部通过，0 跳过**；60 条离线解析完全匹配、原始 30 条行为匹配 30/30。会话/生命周期连续演示、并发与回滚检查通过；Chrome 实际验证了多轮修改、刷新恢复和确认分配。官方基线未改变；速度目标标准场景平均 8.05 天、迟交 1.67%，成本和部分质量指标存在基线更优的情况，完整对比见上方报告。

完整证据：[verification_summary.json](evaluation/results/verification_summary.json)。离线指标和真实在线结果分开记录，不代表独立 holdout 集的泛化能力。

## 当前范围

业务日期默认 `2026-04-01`。Parser v1 负责单消息，会话层使用显式命令合并；任意多轮自然语言、工坊状态/产能管理、自动过期、独立 holdout 和 30 条解释忠实性人工评估仍待完成。发布版本 v0.3、DB v3、Session v1；原分配 Pipeline 保持 v0.2，避免仅因发布版本变化破坏既有幂等重放。
