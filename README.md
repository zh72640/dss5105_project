# SweaterCo Dispatch Desk — MVP v0.2

自然语言分配 → Parser v1 → SQLite 检索 → 工坊资格/队列 → 单工坊或整数拆单 → 事务写库 → 页面/JSON 结果。本版进一步支持**部分/全部完工、撤销分配、失效、重派**，保留已完工件数，配合版本检查、幂等和操作审计。

默认使用**离线规则解析**，无需第三方 Python 包。真实 LLM 使用 **Google 官方 `google-genai` SDK / `gemini-3.5-flash`**，仅从 `GEMINI_API_KEY` 读取密钥。2026-10-02 真实请求已成功，完整 60 条评估因 46 条 HTTP 429 未达验收标准；详情见[在线验收记录](docs/GEMINI_LIVE_ACCEPTANCE_CN.md)。

## 立即运行

在项目目录执行（Python 3.10+；验证环境为 3.14.3）：

```bash
# 同一临时持久库演示分配、部分完工、撤销、重新分配、重派和完工
python3 -m demos.lifecycle_demo

# 启动页面
python3 -m app.server
```

浏览器打开 <http://127.0.0.1:8000>。首次启动从 CSV 初始化 `runtime/dispatch.sqlite3`，以后保留状态。旧 v1 库自动事务升级到 migration 002；请先停服务备份旧库。演示脚本使用独立临时库，不重置 runtime。

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

- [系统说明与手动操作](docs/SYSTEM_GUIDE_CN.md)：环境、页面、CLI/API、模型和排错。
- [生命周期规则与接口](docs/LIFECYCLE_CN.md)：数量、队列、迁移、状态、审计及操作示例。
- [本次变更与验收](docs/CHANGELOG_LIFECYCLE_CN.md)：本轮逐项提交、文件变化和验证证据。
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

**150 条自动测试全部通过，0 跳过**，包括 11 条官方 SDK 模拟网络测试、27 条生命周期/迁移专项测试、HTTP 和 CLI 验收。60 条离线解析完全匹配，原始 30 条行为匹配 30/30，官方 standard/shock 模拟器基线未改变。生命周期连续演示的数量、队列、外键与重放检查均通过，Chrome 实际完工/重派操作通过。

完整证据：[verification_summary.json](evaluation/results/verification_summary.json)。离线指标和真实在线结果分开记录，不代表独立 holdout 集的泛化能力。

## 当前范围

业务日期默认 `2026-04-01`；Parser 仍是单消息模式。Session 多轮澄清、工坊状态/产能管理、自动过期、新分配器的官方模拟器比较留待下一阶段。原始数据、官方 harness 和 Week 4 基线保持不变。
