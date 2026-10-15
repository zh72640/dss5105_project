# 项目开发约定（草稿）

本文适用于整个仓库，供 Codex 及其他开发 Agent 阅读。

- `docs/architecture.md` 是目标系统架构的设计依据。
- 当前代码与测试用于确认已有业务行为和兼容性要求，不作为目标架构的判定标准。
- `AGENTS.md` 提供核心开发约束；具体 Tool 和 Skill 的开发方式遵循对应规范。
- 当现有实现与目标架构冲突时，应先识别差异并制定迁移方案，不得自行修改架构原则来适应旧代码。

## 1. 项目定位

- 本项目面向快反服装制造的外协派单场景，通过自然语言交互协助工厂选择合适的外部工坊，提供可解释、可追溯的分配建议与决策记录。
- 系统支持订单与约束提取、信息澄清、工坊资格和可行性评估、交期估算、备选方案推荐及分配确认，帮助派单员在时间压力下作出决策。
- 派单综合考虑工坊能力、产能、队列、质量、成本与交付约束。LLM 负责请求理解、任务协调和结果解释；关键业务规则、计算与状态变更由确定性代码控制。

## 2. Project Structure

以下是目标目录职责。现有代码尚未全部迁移到这些位置；开发新功能时遵循此分层，调整旧功能时核对调用方与兼容性，不因目录调整复制业务实现。

| 目录 | 目标职责 |
| --- | --- |
| `app/agent/` | Agent 执行、LangGraph 节点与路由、State 管理、Skill 加载、Tool 调度、暂停与恢复。 |
| `app/skills/` | Markdown Skill，定义业务任务的步骤、工具使用、分支、澄清和 Fallback 方法。 |
| `app/tools/` | 向 Agent 暴露标准化能力；验证输入、调用 Service 或 DB Repository，并封装结构化结果。 |
| `app/services/` | 确定性业务操作、计算、评分、优化算法、业务规则和执行策略。 |
| `app/db/` | 所有数据库访问，包括 SQL、CRUD、Repository、连接、事务及迁移。 |
| `app/prompts/` | 独立管理 LLM Prompt 模板及加载逻辑。 |
| `app/schemas/` | HTTP、Agent State、Tool 输入输出及业务数据契约。 |
| `app/api/` | FastAPI 接口、HTTP 请求处理和响应。 |
| `app/config/`、`app/core/` | 通用配置、应用基础设施、模型客户端和安全机制。 |

上表是后续开发与重构的目标，不表示代码已经全部迁移。现有目录位置及其与目标分层的差距见 `docs/current_architecture.md`；其他目录继续承担各自的命令、页面、数据、验证和运行文件职责。

## 3. 架构原则与职责边界

本项目采用 **Agent–Skill–Tool–Service** 分层架构。`docs/architecture.md` 是目标架构的详细设计依据；当前代码中不符合该架构的实现，不作为后续开发的设计标准。

### 3.1 组件职责

- **LLM Agent**：负责理解用户请求、根据 Skill 选择 Tool、分析结果、提出下一步行动及生成解释。不直接实现业务计算、SQL 或状态变更。
- **LangGraph Runtime**：负责节点执行、路由、Agent–Tool Loop、State 管理、流程守卫、暂停与恢复。LLM 提出行动，Runtime 控制实际执行。
- **Skill**：以 Markdown `SKILL.md` 描述任务步骤、Tool 使用、条件分支、澄清和 Fallback。Skill 是动态加载的指导资源，不是可执行 Python Workflow，不授予权限，也不能替代确定性业务规则。
- **Tool**：向 LLM 暴露独立、具名、可调用的能力，负责参数与调用条件校验、下层能力调用及结构化结果封装。不重复实现 Service 中的计算和规则，不直接编写 SQL。
- **Service / Policy**：执行确定性业务操作，包括资格判断、约束校验、交期估算、评分、规划和状态变更。必须独立执行业务校验，不依赖 Agent 或 Tool 已完成的检查。
- **DB Repository**：统一负责 SQL、CRUD、连接、事务与持久化，不决定派单策略。
- **Prompt**：独立管理模型提示模板，通过 Loader 加载；不在 Agent 主流程中硬编码大量 Prompt 或确定性业务规则。

### 3.2 执行与依赖规则

- **Main Graph 与业务流程分离。** Main Graph 负责通用任务识别、路由及结果处理；业务专属准备步骤、规则和完成条件归业务节点或 Subgraph。
- **Intent、Business Task 和 Skill 不强制一一对应。** 业务流程按需加载零个、一个或多个 Skill，不要求每个 Skill 都有独立 Agent 或 Subgraph。
- **Agent Executor 应可复用。** 模型调用、Tool Binding 和 Agent–Tool Loop 使用通用机制；各业务自行定义准备流程、Skill、允许的 Tool 和 Completion Guard。
- **Tool 必须独立组织。** Tool 定义和实现放在 `app/tools/`，通过 Registry 注册，并根据任务和权限动态暴露。不得将业务 Tool 实现集中堆积在 Agent Node 或内部 ToolSet 中。
- **LLM 自主调用业务能力时使用 Tool。** LangGraph 的确定性节点可以直接调用 Service；Tool 可以调用 Service，或通过 DB Repository 执行简单查询。
- **Tool 暴露与执行权限分离。** Skill 声明某个 Tool 不代表获得调用权限。Runtime 必须独立验证 Tool Call，Service / Policy 负责最终业务规则校验。
- **LLM 不能自行宣告任务成功。** 模型停止调用 Tool 不代表任务完成；业务流程必须通过 Completion Guard 核对必要结果。
- **统一任务结果。** 业务流程通过 `TaskResult` 向 Main Graph 返回结构化结果，不允许依据模型文本直接修改业务状态。
- **业务数据与工作流状态分离。** SQLite 业务表是订单、队列、推荐、分配和业务任务状态的权威来源；LangGraph checkpoint 保存工作流执行上下文，不代替业务数据库。

### 3.3 业务与兼容性约束

- **推荐、确认和提交必须分离。** Chat v2 推荐仅为预览；分配提交必须通过携带推荐 ID 和当前版本信息的显式 `confirm` 操作，并重新验证身份、版本及最新业务事实。
- **关键写操作必须受控。** 业务状态变更需要 Service / Policy 校验、数据库事务、版本检查、审计及适当的幂等保护。模型回复不能替代实际提交结果。
- **对话以 Chat v2 为准。** 自然语言分配走 `/api/chat/*` 与 `/chat`；`offline` 与 `llm` 仍是 Chat 内不同模式，不是旧 Parser/Session 产品。Parser v1（`/api/requests`）、旧多轮 `/api/sessions` 与 `session_revise` jobs 已退役，不得再恢复为对外 API。
- **生产状态规则必须复用。** 生产事件沿用 `app/services/lifecycle.py` 的状态、数量、版本、审计与幂等规则；Agent Tool 不得另行实现生产状态变更逻辑。本地测试可用 `dispatch.seed_allocation`（离线规则）准备已分配订单，它不是 HTTP 产品入口。
- **Desk 引导至 Chat。** Desk「新建请求」等会话编辑入口应跳转 `/chat`；推荐确认继续走 Chat 推荐卡语义，不重建旧 `/api/sessions` 编辑器。
- **重构优先复用既有实现。** 不在 Agent、Tool 和 Service 中复制同一业务规则，不因架构调整擅自改变算法、接口行为或数据库语义。发现现有实现与目标架构冲突时，先分析差距并制定迁移方案。

## 4. Tool & Skill Development

- 新增或修改 Tool 时，遵循 `docs/tool_development.md`。
- 新增或修改 Markdown Skill 时，遵循 `docs/skill_development.md`。
- Tool 仅暴露能力，不复制 Service 的业务计算和确定性规则。
- Skill 仅定义任务执行指引，不替代 LangGraph 流程守卫或 Service / Policy。
- 修改 Tool 或 Skill 时，应同步验证相关 Schema、Registry、调用权限及业务测试。

## 5. 数据、安全与运行环境

- 不提交 `.env`、API 密钥、个人 CSV、运行中的 SQLite 数据库、备份或登录凭据。`.env.example` 只放字段说明和空值；配置在启动时读取，运行中的模型调用使用该配置快照。
- 测试、演示和评估优先使用临时或独立数据库，绝不把默认 `runtime/dispatch.sqlite3` 当成可清空的测试库。修改真实数据库或运行迁移前先确认目标路径和备份状态。
- 保留 Chat 会话的 owner 检查、HTTP 鉴权、管理员角色边界、版本冲突与请求 ID 重放规则。账号共享当前业务工作区；不要假设已经实现多租户隔离。
- 默认服务器只监听本机 `127.0.0.1`。外部模型调用是可选的在线验证，需明确区分于 mock 或离线测试。

## 6. 开发与验证

从仓库根目录运行命令。常用入口：

```bash
uv sync --locked
uv run --locked python -m app.cli.setup
uv run --locked python -m app.server --backend offline
```

根据改动范围先运行相关测试，再考虑完整回归：

```bash
uv run --no-sync python -X utf8 -m unittest tests.test_dynamic_agent -q
uv run --no-sync python -X utf8 -m unittest discover -s tests -p "test_*.py" -q
node tests/test_chat_ui.cjs
node tests/test_ui_state.cjs
```

只修改文档时检查文件路径、链接、命令及描述是否与当前实现一致。修改 Agent、Tool、事务或状态机时，至少覆盖成功、拒绝/冲突、重试/重放和旧数据恢复中与变更相关的路径。`evaluation/verify_*.py` 中部分脚本会写入 `evaluation/results/`；运行前确认是否需要更新报告，不要把历史结果当作本次测试结果。

对涉及多个模块的架构调整，必须先阅读相关 Architecture 和开发规范，分析现有实现与目标架构的差距，制定文件级迁移计划，再分阶段实施和验证。优先复用既有代码，不进行无关重构。

**Language Convention**：整个系统面向英文用户。所有用户可见内容，包括 UI 文案、Agent 回复、澄清问题、错误提示及推荐解释，必须使用英文。代码标识符、注释、Docstring、Prompt、Skill 和开发文档原则上也使用英文；不得新增中文硬编码文案。`AGENTS.md` 和现有中文架构文档可保留中文，无须为此翻译。

## 7. 交付说明

完成变更时说明：改了哪些文件、行为为何变化、运行了哪些验证、哪些验证因环境或外部模型不可用而未运行。涉及模型或模拟器的结论要写明使用真实服务、mock、离线规则还是固定种子数据。若发现已有未提交修改与任务冲突，先定位冲突范围，避免覆盖其他人的工作。
