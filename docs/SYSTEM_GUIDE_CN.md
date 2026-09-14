# 当前系统说明与操作手册

版本：Week 5/6 MVP v0.1，Parser/Prompt v1，SQLite migration 001。实际工作目录是 `Workspace`（不是另建 `WorkSpace`）。

系统已支持从一条自然语言消息完成解析、真实订单检索、资格筛选、队列计算、单工坊或整数拆单、数据库事务更新和页面显示。默认是可重复的离线规则模式；LLM 接口代码已实现，服务商已固定为 Google Gemini / gemini-2.5-flash；当前环境缺少 GEMINI_API_KEY，在线验收尚待运行。**离线成功不代表真实模型验收已经完成。**

## 1. 环境与首次运行

Python 3.10 或以上；此次在 macOS / Python 3.14.3 验证。离线核心和 SQLite 使用 Python 标准库，无需 pip 安装。Google Gemini 模式和 SDK 专项测试需安装 requirements.txt 中固定版本的 google-genai；建议使用项目 .venv。读取计划 PDF 时用过的 pypdf/pymupdf 只是开发工具，不是系统运行依赖。

打开终端，进入项目：

```bash
cd '/Users/moxit/Desktop/NUS/Semester 1/DSS5105/Final_Project/Project/Workspace'
python3 --version
python3 -m demos.week6_demo
```

demo 每次新建并自动清理一个临时数据库，无需手动删除数据。正常看到：

- 导入 120 orders、8 workshops。
- 示例 `ORD-045 / min_cost / exclude W3 / max 2` 成功分给 FreshStart（W8），150 件，成本 150，预计 3.5 天。
- requests、request_parsing_history、working_order、decision_log 各 1 行。
- `replay_is_idempotent: true`，再次提交相同 key 不增加记录或队列。

这些数值对应干净快照。已有队列或不同目标下，推荐和时间会改变。

## 2. 使用页面

```bash
python3 -m app.server
```

在浏览器手动打开 <http://127.0.0.1:8000>。关闭服务时在终端按 `Ctrl+C`；数据库会保留。端口占用可换为：

```bash
python3 -m app.server --port 8001
```

首次自动生成 `runtime/dispatch.sqlite3` 并导入 CSV，后续启动不会覆盖数据。页面显示当前 backend 和业务日期；输入完整消息后点击“执行分配并保存”。成功分配立即记入本地数据库。

页面包含：请求和默认目标、分配工坊及件数/费用/天数、单工坊候选比较、排除原因、预计日期和提示、最近 30 条请求、解析 JSON 与完整审计记录。界面以中文标注，机器 reason codes 和部分解释保留英文，便于和测试/日志对应。

每次成功收到响应后，下一次点击会生成新的 request_id；同一已分配订单会被 WORKING 状态保护。只有网络失败后原输入重试，页面才复用同一 request_id，避免重复写库。

可独立测试的输入：

```text
Allocate ORD-045 using the fastest workshop. Cost doesn't matter.
Allocate ORD-093 fastest; at most two workshops.
Allocate ORD-109 cheapest; exclude BudgetWorks.
Please allocate the urgent order.
Send ORD-073 to FreshStart.
Cancel order ORD-045.
```

第一条在干净库推荐 Nimble Needle，150 件，费用 180，预计 3.1538 天。第二条允许最多两个工坊，干净库会拆成 Little Loom 58 件、Nimble Needle 42 件，预计约 2.3286 天，并提示该订单已过目标交期。消息里的“最多两个”允许系统只用一个；不代表必须拆单。

`CLARIFY` 时，需要你核对订单号/数量/日期，并**重新提交一条完整消息**。暂不支持只回答“就是那个”或“改成两个”的多轮会话。

## 3. 命令行

```bash
# 原始请求 R09，隔离运行（不持久化）
python3 -m app.cli --request R09 --db :memory:

# 自由消息，写入默认运行数据库
python3 -m app.cli --message 'Allocate ORD-045 cheapest; exclude W3; at most two workshops.' --request-id cli-demo-001

# 不同的持久化演示数据库
python3 -m app.cli --request R25 --db runtime/another-demo.sqlite3 --request-id r25-demo-001

# 只允许一个工坊时，业务默认目标是 min_delay
python3 -m app.cli --message 'Allocate ORD-073.' --objective min_cost --db :memory:

# 显式业务日期（必须不早于数据库队列快照）
python3 -m app.cli --request R09 --as-of 2026-04-02 --db :memory:
```

`--request R09` 只是读取 data/dispatch_requests.txt 中的那条原文；`--request-id` 才是每次提交的幂等标识。

支持目标 `min_delay / min_cost / min_defects / hybrid`；旧 `min_lateness / fastest_turnaround` 会映射为 min_delay。消息中明确目标优先于 CLI 默认目标。输出统一 JSON；系统 ERROR 时 CLI 退出码为 1，业务 CLARIFY/REFUSE/DECLINE/ESCALATE 是正常返回，退出码为 0。

## 4. 使用指定的 Google Gemini 模型

本次配置已经固定：

| 项目 | 值 |
|---|---|
| 服务商 / SDK | Google Gemini Developer API / 官方 `google-genai==2.23.0` |
| 模型 | `gemini-2.5-flash`，代码固定，不读取其他模型变量 |
| API 地址 | `https://generativelanguage.googleapis.com`，官方默认地址 |
| 调用 | 官方 SDK `client.models.generate_content()`，API v1beta |
| 密钥来源 | **仅 `GEMINI_API_KEY`**，通过 `genai.Client(api_key=...)` 显式传入 |
| 结构化输出 | application/json + response_json_schema；保留 Parser v1 业务校验 |
| 重试 | SDK attempts=1；外层 Parser 最多重试 1 次，总计最多 2 次生成调用 |
| 其他参数 | temperature=0；thinking_budget=0；输出上限4096 tokens；默认超时30秒 |

不使用 OpenAI 兼容端点、Vertex AI、LLM_API_KEY 或 OPENAI_API_KEY；即使其他 Google 变量已配置，也显式选择 Gemini Developer API 和指定 key。无需设置 Base URL。SDK 的官方调用示例及 JSON Schema 说明见 [Google Python SDK](https://googleapis.github.io/python-genai/)。

从 Workspace 执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 在当前终端交互输入密钥，避免写入 shell 历史
printf 'Gemini API key: '
read -r -s GEMINI_API_KEY
printf '\n'
export GEMINI_API_KEY
export GEMINI_TIMEOUT_SECONDS=30

# 先进行隔离请求，再启动页面
python -m app.cli --backend llm --request R09 --db :memory:
python -m app.server --backend llm
```

如果你已经在该终端 export 了 GEMINI_API_KEY，跳过交互输入即可。`.env.example` 只是说明，应用**不自动读取 .env**。在另一个终端设置的变量不会自动传入已经运行的服务或 Codex 进程；请在已 export 的同一终端启动/重启应用。不要把密钥粘贴到聊天或提交进 Git。

默认 `python -m app.server` 仍是 offline；显式 `--backend llm` 或 `export PARSER_BACKEND=llm` 启用 Gemini。切换后，当前请求会发送给 Google 并可能消耗 API 配额；全量订单库不进入 Prompt。模型只做提取，分配、费用、队列和 ETA 仍由本地代码决定。

Gemini 适配将冻结 schema 中 nullable enum 转为语义等价的 JSON Schema anyOf；Parser 字段、Prompt v1 和数据库结构没有改名或重定义。所有用户 few-shot 和输入转为 SDK 的 user/model content，system rules 与重试诊断放入 system_instruction。

### 在线验收

```bash
# 一条真实链路 + 相同 key 重放检查，最多2次生成调用
python evaluation/verify_gemini_live.py

# 加跑60条真实LLM测试，最多额外120次生成调用
python evaluation/verify_gemini_live.py --full
```

输出默认在 `evaluation/live_results/`（已忽略提交）；包含在线状态、完整 demo、full 模式下的逐条 raw/validated 输出和指标。缺 key 时状态为 NOT_RUN 并返回退出码1，SMOKE_PASSED 只代表单条端到端成功；只有 full 模式达到计划指标才标 ACCEPTANCE_PASSED。

也可单独运行 `python evaluation/evaluate_parser.py --backend llm --output-dir evaluation/live_results`。不要用 offline 指标替代在线验收。此次 `evaluation/results/gemini_live_status.json` 明确记录 `gemini_api_key_missing`，未发起真实 API 请求。

## 5. 自动验证与证据

```bash
python3 evaluation/verify_mvp.py
```

请在安装 requirements.txt 的虚拟环境内运行。这一命令运行 116 条测试、60 条解析回归、30 条原始语言行为回归、Week 5 mock demo、Week 6真实数据 demo、官方标准与 shock 模拟器比对；报告写到 `evaluation/results/`，失败返回非零。

也可分别运行：

```bash
python3 -m unittest discover -s tests -v
python3 evaluation/evaluate_parser.py --backend offline
python3 evaluation/evaluate_dispatch.py
python3 -m demos.week5_mock
python3 -m demos.day1_retrieval
```

HTTP 测试会短暂监听 `127.0.0.1` 随机端口；在受限执行沙箱中需允许本地端口监听。不会连接外部模型或修改默认 runtime 数据库。若未安装 SDK，10 条 Google SDK 专项测试会明确跳过，summary 的 tests_skipped 不为0，不能把该运行称为完整验收。官方 baseline_results.txt 保留原样，验收脚本只比对，不覆盖。

## 6. HTTP 与代码接口

服务仅监听本机，作为课程演示接口，不是带认证的公网系统。

| 路径 | 方法 | 作用 |
|---|---|---|
| / | GET | 页面 |
| /api/health | GET | backend、版本、业务日期 |
| /api/history | GET | 最近 30 次请求概要 |
| /api/requests | POST | 处理并提交一条消息 |

POST Content-Type 必须为 application/json：

```json
{"message":"Allocate ORD-045 cheapest; exclude W3; at most two workshops.","objective":"min_delay","request_id":"api-demo-001"}
```

`message` 必填；objective/request_id 可省略。HTTP 200 表示有正常业务结果，请读取 result.decision_status；409 表示 key 冲突；400/413/415 表示输入问题；503 表示系统/模型/数据库错误。

Python 调用：

```python
from app.pipeline import process_request

response = process_request(
    "Allocate ORD-045 cheapest; exclude W3; at most two workshops.",
    db_path="runtime/dispatch.sqlite3", request_id="python-demo-001", backend="offline",
)
print(response["result"])
```

直接调用不传 db_path/database 时使用独立内存库，便于测试；CLI/server 默认使用持久化文件。服务器不接受 `:memory:`，因为不同请求线程必须共享同一个文件库。

## 7. 数据、人工操作与故障处理

原始 CSV 是初始化种子，不是实时数据库。修改 CSV 不会刷新已经存在的数据库；真实业务数据同步与管理界面留待下一阶段。当前业务日期固定为数据字典的 **2026-04-01**；系统请求日志时间则使用真实 UTC 时间，两者不可混淆。

你需要手动做的事情：

1. 启动服务并打开浏览器；启用在线解析前安装 SDK 并设置 GEMINI_API_KEY；模型已经固定。
2. 对 CLARIFY 请求核对真实订单信息，重新提交完整消息。
3. 对 REFUSE/ESCALATE 查看原因，确认工坊状态或约束后提交新请求。当前系统不会替你发消息联系工坊或安排实际运输。
4. 团队确认逾期/失效、交期硬约束、拆单默认、完工和撤销等业务规则，并核对 Data Schema2 原始定义。
5. 第二位人工复核 60 条 golden case 及原始 30 条行为标签，进行真实 LLM 在线评估。

| 问题 | 处理 |
|---|---|
| ORDER_ALREADY_WORKING | 该订单已分配；重放用原 key，重新演示用临时库/新库；不要只删除某张表的一行 |
| IDEMPOTENCY_CONFLICT | 同 key 搭配了不同消息、目标、日期或模型；新提交使用新 key |
| ORDER_FIELD_CONFLICT | 明确给出的数量/日期等与订单表不同；先核实，不自动覆写主数据 |
| PARSER_NEEDS_CLARIFICATION | 提供订单 ID、绝对日期或清晰约束；复杂自由表达可改为示例句式 |
| PARSER_ERROR | 查看 result.message 与 parser_telemetry.attempts；按下表处理 Gemini 原因 |
| gemini_api_key_missing | 在启动应用的同一终端 export GEMINI_API_KEY，并重启服务 |
| gemini_sdk_missing | 激活 .venv 后执行 python -m pip install -r requirements.txt |
| gemini_invalid_timeout | GEMINI_TIMEOUT_SECONDS 必须为0到300之间的有限正数 |
| gemini_http_400/401/403/404 | 检查 API key、项目权限、模型可用性/参数；不自动换模型或服务商 |
| gemini_http_429/5xx | 限流/临时服务错误，Parser最多重试一次；仍失败时稍后用新 request_id 重试 |
| gemini_refusal / gemini_incomplete_output | 模型拒绝或输出截断；不会把不完整 JSON 交给分配器 |
| QUEUE_DATA_MISSING | 数据库缺少工坊队列记录；从可信备份恢复或用干净演示库，不默认其空闲 |
| QUEUE_DATE_REWIND | 业务日期早于已保存队列快照；使用同日/后续日期，回放则用新库 |
| DB_ERROR | 检查目录权限、文件路径、锁；响应 error_logged=false 表示数据库审计也未保存 |
| 端口占用 | 更换 --port；浏览器地址随之更改 |

**备份**：先 `Ctrl+C` 停止服务，再复制 `runtime/dispatch.sqlite3` 到你指定的备份路径。恢复时也先停止服务，将完整备份恢复为运行文件；不要在程序运行时仅复制部分 SQLite 辅助文件。当前没有单笔撤销 API。

如果只需重新演示，使用 `python3 -m demos.week6_demo` 最简单；它不会删除或改动你的持久化数据库。

## 8. 当前边界

已实现功能和待办分别见 [验收表](WEEK5_WEEK6_ACCEPTANCE_CN.md)、[已知限制](../KNOWN_ISSUES.md) 和 [下一阶段说明](NEXT_STAGE_CN.md)。目前未实现 Session、自动完工/过期、人工改单/撤销、工坊系统对接和公网部署。模型质量待在线验证；hybrid 是启发式，官方模拟器仍是原始基线，不代表新分配器已经优于三种 baseline。
