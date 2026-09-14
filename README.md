# SweaterCo Dispatch Desk — Week 5/6 MVP v0.1

已从 Week 4 固定样例骨架升级为可运行的单消息系统：自然语言 → Parser v1 → SQLite 检索 → 工坊资格/队列 → 单工坊或整数拆单 → 事务写库 → 页面/JSON 结果。

默认使用**离线规则解析**，无需安装第三方 Python 包。真实 LLM 已适配 **Google 官方 `google-genai` SDK / `gemini-2.5-flash`**，仅从 `GEMINI_API_KEY` 读取密钥。当前执行环境没有该变量，**真实模型调用与质量验收尚未运行**。

## 立即运行

在 `Workspace` 目录执行（Python 3.10+；本次验证版本为 3.14.3）：

```bash
python3 -m demos.week6_demo
python3 -m app.server
```

浏览器打开 <http://127.0.0.1:8000>。演示脚本使用独立临时数据库；服务首次启动将原始 CSV 导入 `runtime/dispatch.sqlite3`，后续运行保留队列和分配状态。停止服务按 `Ctrl+C`。

```bash
# 单次隔离请求，不保留状态
python3 -m app.cli --request R09 --db :memory:

# 持久化请求；重复相同 key/输入只重放结果
python3 -m app.cli --message 'Allocate ORD-045 cheapest; exclude W3; at most two workshops.' --request-id my-demo-001

# 一键验收并生成 evaluation/results/ 下的报告
python3 evaluation/verify_mvp.py
```

## 文档入口

- [系统说明与手动操作](docs/SYSTEM_GUIDE_CN.md)：运行、界面、CLI/API、数据库、真实 LLM 配置、故障处理。
- [本次文件变更日志](docs/CHANGELOG_WEEK5_WEEK6_CN.md)：逐文件列出新增、修改、删除及目的。
- [下一阶段交接说明](docs/NEXT_STAGE_CN.md)：优先级、待确认规则、后续任务和验收条件。
- [Week 5/6 验收对照](docs/WEEK5_WEEK6_ACCEPTANCE_CN.md)：逐项对应两份计划，区分已验证与待外部验证。
- [Parser v1 接口](README_parser.md)、[数据库映射和状态语义](docs/DATABASE_SCHEMA_CN.md)、[已知限制](KNOWN_ISSUES.md)。

## 使用 Google Gemini

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 在当前终端安全设置 GEMINI_API_KEY，详见系统说明；无需设置 Base URL 或模型变量。
python -m app.server --backend llm
```

模型固定为 `gemini-2.5-flash`，使用 Google 官方默认地址。在线冒烟验收：`python evaluation/verify_gemini_live.py`；加 `--full` 才会运行 60 条真实模型评估。离线核心仍可不安装依赖运行；完整 SDK 测试请在上述虚拟环境内执行 `python evaluation/verify_mvp.py`。

## 已验证结果

116 条自动测试通过（包含 10 条真实 Google SDK + 模拟网络专项测试，0 条跳过）；60 条 parser golden case 完整匹配，原始 30 条请求的行为标签匹配 30/30；标准/shock 模拟器与 Week 4 原始基线一致。真实浏览器已完成提交、分配结果、候选表和历史记录的人工检查。

所有解析质量数字都是本仓库**离线回归集**的结果，不是独立测试集或真实 LLM 的泛化能力证明。详见 [验证摘要](evaluation/results/verification_summary.json)。

## 范围

业务日期默认 `2026-04-01`，来自 `data/data_dictionary.md`。Session、多轮澄清、生产完工事件、自动过期、RAG、Agent 编排、复杂混合目标优化和新算法的官方模拟器对比留在下一阶段。原始 `data/`、官方 `harness/`、Week 4 fixtures 和基线均保留
