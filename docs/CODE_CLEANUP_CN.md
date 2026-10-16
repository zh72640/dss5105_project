# 代码清理与迁移说明

This is the **2026-10-14 cleanup record**, not an inventory of the current working tree. Later, uncommitted architecture work added new implementations and compatibility imports. For current paths and next actions, use [current_architecture.md](current_architecture.md) and the [file migration map](app_file_migration_map.md). Do not use the historical table below as an import guide for new code.

| Current canonical responsibility (2026-10-16 working tree) | Path |
| --- | --- |
| Tool contracts and handlers | `app/tools/registry.py`, `app/tools/operations.py`, `app/tools/production.py` |
| Business scoring, eligibility, and planning | `app/services/scoring.py`, `app/services/eligibility.py`, `app/services/planner.py` |
| Database repositories | `app/db/` |
| Prompt loader, resources, and guide | `app/prompts/` |
| Model runtime (LangChain ModelRegistry) | `app/llm/` (direct `core/providers` removed) |
| Data contracts | `app/schemas/` |

Compatibility imports currently remain under `app/agent/models/`, `app/agent/providers/`, `app/agent/prompt_catalog/`, `app/agent/toolset.py`, `app/tools/database/`, and `app/tools/allocator/`. Offline Chat v2, Parser v1, old sessions, and `/api/requests` remain executable compatibility flows. The current prompt catalog manifest has additional Agent and allocation entries; its older copy must not replace it.

2026-10-14：根据用户要求，先迁移当时的仓库调用方，再删除当时废弃的实现和兼容转发。此前尚未提交的业务重构继续保留。

**2026-10-14 清理结果（历史快照）**

当时 app 下 Python 文件从 160 个减少到 91 个。移除 43 个通过 importlib/sys.modules 转发的模块，删除旧包的导出、旧 CSV 分配/查询链路及固定样例解析器。当时的目录结构见 [应用架构](AGENT_ARCHITECTURE_CN.md)；当前目录以 [当前架构](current_architecture.md) 为准。HTTP API、业务 UI、数据库迁移和审批流程继续使用现有实现，该次清理未新增数据库迁移。

同时删除未使用的评分工具、旧 gate_request、空 skills 注册表和未接入评估的 simulate_new.py；删除 runtime_for_database、服务层 identify 转发、Gemini 历史常量属性转发及多余 import。原始 CSV、正式模拟器 simulate.py、数据库迁移、Prompt YAML、当前回归夹具和冻结评估报告保留。

**命令入口**

| 功能 | 当前命令 | 原入口 |
|---|---|---|
| 初始化 | `python -m app.cli.setup` | `python -m app.setup` 已删除 |
| 注册或重置普通账号 | `python -m app.cli.auth USERNAME` | `python -m app.auth` 已删除 |
| 会话操作 | `python -m app.cli.sessions` | `python -m app.session_cli` 已删除 |
| 生产操作 | `python -m app.cli.lifecycle` | `python -m app.lifecycle_cli` 已删除 |
| 单条派单 | `python -m app.cli` 或 `python -m app.cli.dispatch` | 默认派单入口仍可用 |
| 启动服务器 | `python -m app.server` 或 `python -m app.cli.server` | app.server 含实际服务器实现，继续可用 |
| 清理 checkpoint | `python -m app.cli.checkpoints` | 入口继续可用 |

原命令参数继续由相同实现处理。账号命令的实际 main 已从 core.security 移到 cli.auth；core.security 仅提供安全与账号操作函数。仓库外的脚本若使用已删除的旧导入或命令，也需按下表迁移。

**2026-10-14 转发模块迁移表（历史路径，非当前导入建议）**

| 已删除的旧模块 | 正式实现 / 替代入口 |
|---|---|
| `app.agent.deepseek_client` | `app.agent.providers.deepseek_client` |
| `app.agent.draft_edits` | `app.agent.intake.draft_edits` |
| `app.agent.llm_client` | `app.agent.providers.llm_client` |
| `app.agent.normalization` | `app.agent.intake.normalization` |
| `app.agent.parser` | `app.agent.intake.parser` |
| `app.agent.prompts` | `app.agent.intake.prompts` |
| `app.agent.rule_parser` | `app.agent.intake.rule_parser` |
| `app.agent.validator` | `app.agent.intake.validator` |
| `app.allocator.allocator` | `对应旧 CSV 实现已一起删除` |
| `app.allocator.planner` | `app.tools.allocator.planner` |
| `app.allocator.scoring` | `对应旧 CSV 实现已一起删除` |
| `app.assistant_reply` | `app.agent.responses.formatter` |
| `app.auth` | `app.cli.auth；账号函数使用 app.core.security` |
| `app.desk` | `app.services.read_models` |
| `app.domain.allocator.allocator` | `对应旧 CSV 实现已一起删除` |
| `app.domain.allocator.planner` | `app.tools.allocator.planner` |
| `app.domain.allocator.scoring` | `对应旧 CSV 实现已一起删除` |
| `app.integrations.llm.deepseek_client` | `app.agent.providers.deepseek_client` |
| `app.integrations.llm.llm_client` | `app.agent.providers.llm_client` |
| `app.lifecycle` | `app.services.lifecycle` |
| `app.lifecycle_cli` | `app.cli.lifecycle` |
| `app.parsing.draft_edits` | `app.agent.intake.draft_edits` |
| `app.parsing.normalization` | `app.agent.intake.normalization` |
| `app.parsing.parser` | `app.agent.intake.parser` |
| `app.parsing.prompts` | `app.agent.intake.prompts` |
| `app.parsing.rule_parser` | `app.agent.intake.rule_parser` |
| `app.parsing.validator` | `app.agent.intake.validator` |
| `app.pipeline` | `app.services.dispatch` |
| `app.prompts` | `app.agent.prompt_catalog` |
| `app.prompts.models` | `app.agent.prompt_catalog.models` |
| `app.prompts.registry` | `app.agent.prompt_catalog.registry` |
| `app.prompts.renderer` | `app.agent.prompt_catalog.renderer` |
| `app.repositories` | `app.tools.database` |
| `app.repositories.order_repository` | `app.tools.database.order_repository` |
| `app.repositories.queue_repository` | `app.tools.database.queue_repository` |
| `app.repositories.workshop_repository` | `app.tools.database.workshop_repository` |
| `app.responses` | `app.agent.responses` |
| `app.responses.formatter` | `app.agent.responses.formatter` |
| `app.responses.templates` | `app.agent.responses.templates` |
| `app.session_cli` | `app.cli.sessions` |
| `app.sessions` | `app.services.sessions` |
| `app.setup` | `app.cli.setup` |
| `app.workflows` | `app.agent.router` |
| `app.workflows.checkpointer` | `app.agent.router.checkpointer` |
| `app.workflows.graph` | `app.agent.router.graph` |
| `app.workflows.nodes` | `app.agent.router.nodes` |
| `app.workflows.nodes.conversation` | `app.agent.router.nodes.conversation` |
| `app.workflows.state` | `app.agent.router.state` |

**删除文件清单**

下列路径记录当时删除；其中一些路径在后续重构中重新出现。最终业务实现与当前路径见 [文件迁移表](app_file_migration_map.md)。旧路径以文字保留，便于检查历史记录。

- `app/agent/conversation.py`
- `app/agent/deepseek_client.py`
- `app/agent/draft_edits.py`
- `app/agent/legacy_parser.py`
- `app/agent/llm_client.py`
- `app/agent/normalization.py`
- `app/agent/parser.py`
- `app/agent/prompts.py`
- `app/agent/rule_parser.py`
- `app/agent/skills/__init__.py`
- `app/agent/skills/protocol.py`
- `app/agent/skills/registry.py`
- `app/agent/validator.py`
- `app/allocator/__init__.py`
- `app/allocator/allocator.py`
- `app/allocator/planner.py`
- `app/allocator/scoring.py`
- `app/assistant_reply.py`
- `app/auth.py`
- `app/desk.py`
- `app/domain/allocator/__init__.py`
- `app/domain/allocator/allocator.py`
- `app/domain/allocator/planner.py`
- `app/domain/allocator/scoring.py`
- `app/http/__init__.py`
- `app/http/status.py`
- `app/integrations/__init__.py`
- `app/integrations/llm/__init__.py`
- `app/integrations/llm/deepseek_client.py`
- `app/integrations/llm/llm_client.py`
- `app/lifecycle.py`
- `app/lifecycle_cli.py`
- `app/parsing/__init__.py`
- `app/parsing/draft_edits.py`
- `app/parsing/normalization.py`
- `app/parsing/parser.py`
- `app/parsing/prompts.py`
- `app/parsing/rule_parser.py`
- `app/parsing/validator.py`
- `app/pipeline.py`
- `app/prompts/README.md`
- `app/prompts/__init__.py`
- `app/prompts/models.py`
- `app/prompts/registry.py`
- `app/prompts/renderer.py`
- `app/repositories/__init__.py`
- `app/repositories/order_repository.py`
- `app/repositories/queue_repository.py`
- `app/repositories/workshop_repository.py`
- `app/responses/__init__.py`
- `app/responses/formatter.py`
- `app/responses/templates.py`
- `app/schemas/allocation.py`
- `app/schemas/candidate.py`
- `app/schemas/request.py`
- `app/session_cli.py`
- `app/sessions.py`
- `app/setup.py`
- `app/tools/allocation.py`
- `app/tools/allocator/allocator.py`
- `app/tools/allocator/scoring.py`
- `app/tools/data.py`
- `app/tools/delivery.py`
- `app/tools/orders.py`
- `app/tools/workshops.py`
- `app/workflows/__init__.py`
- `app/workflows/checkpointer.py`
- `app/workflows/graph.py`
- `app/workflows/nodes/__init__.py`
- `app/workflows/nodes/conversation.py`
- `app/workflows/state.py`
- `harness/simulate_new.py`

当时 Prompt 使用说明从 `app/prompts/README.md` 移至 `app/agent/prompt_catalog/README.md`。当前正式说明已回到 [app/prompts/README.md](../app/prompts/README.md)，正式 Repository 位于 `app/db/`。冻结样例仍可用于验证提示词与用户回复内容；旧测试导入路径需按文件迁移表逐步更新。

历史 release manifests、评估结果及 changelog 记录当时的文件路径和哈希，不因本次文档核对而重写。当前使用说明以当前架构和文件迁移表为准。

**2026-10-14 验证记录（不是本次文档核对的测试结果）**

- 完整 Python 回归：283 项全部通过，覆盖账号、HTTP、会话、审批、后台 jobs、迁移、模型 mock、生产操作和 CLI；最后一轮耗时 121.464 秒。
- 前端控制器：11 项全部通过。
- 7 个 CLI 入口的 --help 检查全部通过；454 个本地导入符号均可解析。
- 当时检查的 130 个 Python 文件语法通过；当时没有残留 importlib/sys.modules 兼容转发，文档链接检查通过。后续重构再次加入了兼容别名。
- 与清理前工作区快照比较，当前 planner、SQLite 数据访问、数据库初始化及 Parser v1 定义保持原文；派单、生产和会话服务的业务语法树保持一致（只调整 import）。
- HTTP 测试在沙箱内因 Windows socket 初始化受限而阻塞，已在获得批准的本机环境完成。模型连接使用测试 mock，没有在线质量评估。
