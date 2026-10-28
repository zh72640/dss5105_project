# 未使用代码排查清单

此文记录清理前的状态。2026-10-14 已按用户要求实施清理；删除文件、正式路径和验证结果见 [代码清理与迁移说明](CODE_CLEANUP_CN.md)。以下旧接口描述仅为排查记录。

排查日期：2026-10-14。依据当前工作区，包括尚未提交的三轮重构成果；没有修改或删除业务代码。

核查了 `app` 的 160 个 Python 模块，以及 23 个测试模块、5 个演示模块、10 个评估脚本、2 个模拟器脚本。检查包括 Python 导入和函数引用、动态导入、包的导出、命令行入口、FastAPI 路由、LangGraph 动态节点注册、网页脚本引用及文档中的兼容约定。

本文“没有调用方”指当前仓库内没有找到实际调用，不能证明仓库之外的代码或手动运行从未使用。是否移除历史接口，应与兼容范围一起决定。

**1. 当前仓库内没有调用方的代码**

| 文件 / 位置 | 未使用部分 | 判断依据 | 处理优先级 |
|---|---|---|---|
| `app/tools/allocation.py`，L4、24、46、63 | `get_estimated_completion_time`、`get_lateness_score`、`get_defect_score`、`get_hybrid_score`，共 84 行 | 没有任何模块导入此文件；四个函数仅在文件内部互相调用。`simulate_new.py` 中的同名方法是独立实现，没有调用本文件。当前业务分配调用 `tools/allocator/planner.py::plan`。 | 高，可优先清理候选 |
| `app/agent/conversation.py`，L7 | `gate_request`，文件共 28 行 | API、会话服务、演示和测试均不调用；当前会话走 `agent/router`。旧文档提及该接口，因此属于历史兼容遗留。 | 高，退役旧接口时归档 |
| [app/agent/models/registry.py](../app/agent/models/registry.py)，L78 | `runtime_for_database` | 只有定义，没有引用；当前后台执行使用 `background_runtime()`。`register_runtime`、`unregister_runtime` 和 `background_runtime` 仍使用同一个注册表。 | 高，仅该函数是候选 |
| [app/services/auth.py](../app/services/auth.py)，L6 | `identify` 转发函数 | HTTP 登录使用此服务的 `identify_principal`；身份依赖直接使用 `core/security.py::identify_principal`。测试调用的 `app.auth.identify` 转发到 `core/security.py`，并未经过此函数。 | 高，仅服务层转发函数是候选 |

**2. 旧 CSV 分配链路：当前不执行，但仍保留兼容导出**

当前业务入口在 `services/dispatch.py` L79 调用 `plan()`，从 SQLite repositories 读取订单与队列。下列旧链路读取原始 CSV，使用旧版 dataclass；没有找到实际调用旧 `allocate()` 的入口。

| 文件 / 位置 | 未使用或仅为旧链路服务的部分 | 关联关系 |
|---|---|---|
| `app/tools/allocator/allocator.py`，L8 | `allocate`，24 行 | 仍被 `app/tools/allocator/__init__.py` 和旧 allocator 包导出；包导入会加载文件，不代表执行分配函数。 |
| `app/tools/allocator/scoring.py`，L5、15 | `score`、`with_score`，17 行 | 仅旧 `allocate` 使用，不是当前 `planner.py` 的评分实现。 |
| `app/tools/delivery.py`，L7 | `estimate_candidate`，16 行 | 仅旧 `allocate` 使用。 |
| `app/schemas/allocation.py` | `DecisionStatus`、`AllocationResult`，31 行 | 旧分配器与旧 `gate_request` 的输出类型，经 `schemas/__init__.py` 导出。 |
| `app/schemas/candidate.py` | `CandidateMetrics`，22 行 | 旧交期估算、旧评分及旧结果类型使用。 |
| `app/schemas/request.py` | `Constraint`、`StructuredRequest`，31 行 | 旧 `legacy_parser`、`gate_request`、旧分配器及类型注解使用；当前解析结果是 `parser_schema.py::ParseResult`。 |

这 6 个文件共 141 行，应按旧链路整体评估，同时处理包导出、旧路径转发和文档。不能把同目录的 `planner.py` 一起删除：它仍是实际分配器。

相关但仍有测试调用的文件：

- `app/tools/orders.py::resolve_order`：`tests/test_tools.py` L11 调用。
- `app/tools/workshops.py::get_workshop`：`tests/test_tools.py` L16、19 调用。
- `app/tools/data.py`：上述查询工具调用 CSV 加载函数；旧分配器也依赖它。
- `app/tools/models.py::Order`：旧 CSV 工具仍需要；同文件的 `Workshop` 被当前 SQLite repository、planner 测试和模拟器适配器使用，整个文件必须保留。
- `app/tools/eligibility.py::exclusion_reason`：当前 `planner.py` L5 直接依赖，仍在业务主链路。

**3. Week 4 固定样例解析器：目前只有兼容声明，没有实际调用入口**

| 文件 / 位置 | 内容 | 判断 |
|---|---|---|
| [app/agent/intake/parser.py](../app/agent/intake/parser.py)，L105 | `fake_parse_request` | 仓库内没有调用；函数内部动态导入旧解析器，因此静态扫描会显示旧解析器“被引用”，但这条路径目前没有执行入口。 |
| `app/agent/legacy_parser.py`，L15 | `parse_request` 及 `_request_id` | 只被上面的兼容函数调用；按 R09、R25 等标签返回固定样例，未进入当前业务流程。 |
| 同文件 L41 | 第二个 `fake_parse_request` | 只有定义，连上面的兼容入口也没有使用它。 |

`README_parser.md` L80 和 `docs/schema_contracts.md` 明确保留这些接口供 Week 4 兼容；适合整体移入历史目录或在退役兼容接口时删除。

**4. 尚未接入的功能与独立实验脚本**

| 文件 / 目录 | 现状 | 建议分类 |
|---|---|---|
| `app/agent/skills/`：`__init__.py`、`protocol.py`、`registry.py` | 共 48 行；没有外部导入、没有已注册技能、router 没有调用注册表，现有测试也没有覆盖。 | 明确的预留骨架。`AGENT_ARCHITECTURE_CN.md` 说明“当前空注册”，不能据此说是被重构淘汰的功能；若近期不做技能系统，可暂时移出业务目录。 |
| `harness/simulate_new.py` | 296 行；独立命令行脚本，有自己的三种新增策略。评估、验收及测试均使用 `harness/simulate.py`，没有引用它。 | 独立实验脚本，未接入当前评估。保留手动实验用途时建议移入实验目录，不能仅因没有 import 就断言不能使用。 |
| `app/http/status.py` | 1 行，仅重新导出 `app.api.status` 的 4 个函数；仓库内没有调用方。 | 空闲的旧 HTTP 兼容入口。文档承诺旧路径保留，退役时连同 `app/http/__init__.py` 一起处理。 |

**5. 文件内部没有使用的 import**

| 文件 / 位置 | 多余导入 | 说明 |
|---|---|---|
| `app/cli/dispatch.py` L3 | `os` | 文件内没有使用。 |
| `app/services/dispatch.py` L4 | `os` | 文件内没有使用。 |
| `app/agent/intake/parser.py` L3 | `os` | 文件内没有使用。 |
| `app/services/lifecycle.py` L10 | `OBJECTIVES` | 校验已由 `domain/lifecycle.py::check_arguments` 完成。 |
| 同文件 L12 | `ACTIONS` | 本文件没有使用；定义本身在 `domain/lifecycle.py` 仍使用。 |
| `app/services/sessions.py` L15 | `merge_followup` | 使用位置已在 `agent/router/nodes/conversation.py` L79；函数本身仍需要。 |
| `app/agent/responses/formatter.py` L2 | `REPLY_HELP` | 本文件没有使用，仓库内也没有读取 `formatter.REPLY_HELP`；可能构成历史模块的隐式导出。`templates.py` 中的常量仍被会话服务使用。 |

共 7 个导入名、涉及 6 个文件。这里列的是 import 冗余，不是建议删除被导入的函数或常量。

**6. 重构后保留的兼容转发文件：共 43 个，不等于 43 个废弃文件**

这些文件通过 `importlib.import_module` 和 `sys.modules` 转发到实际实现。很多路径仍被 services、测试、演示或 CLI 使用。下面是完整文件清单；其中一部分形成两层转发。

| 兼容文件 | 转发目标 |
|---|---|
| `app/assistant_reply.py` | `app.responses.formatter` |
| `app/auth.py` | `app.core.security` |
| `app/desk.py` | `app.services.read_models` |
| `app/lifecycle.py` | `app.services.lifecycle` |
| `app/lifecycle_cli.py` | `app.cli.lifecycle` |
| `app/pipeline.py` | `app.services.dispatch` |
| `app/sessions.py` | `app.services.sessions` |
| `app/session_cli.py` | `app.cli.sessions` |
| `app/setup.py` | `app.cli.setup` |
| `app/agent/deepseek_client.py` | `app.integrations.llm.deepseek_client` |
| `app/agent/draft_edits.py` | `app.parsing.draft_edits` |
| `app/agent/llm_client.py` | `app.integrations.llm.llm_client` |
| `app/agent/normalization.py` | `app.parsing.normalization` |
| `app/agent/parser.py` | `app.parsing.parser` |
| `app/agent/prompts.py` | `app.parsing.prompts` |
| `app/agent/rule_parser.py` | `app.parsing.rule_parser` |
| `app/agent/validator.py` | `app.parsing.validator` |
| `app/allocator/allocator.py` | `app.domain.allocator.allocator` |
| `app/allocator/planner.py` | `app.domain.allocator.planner` |
| `app/allocator/scoring.py` | `app.domain.allocator.scoring` |
| `app/parsing/draft_edits.py` | `app.agent.intake.draft_edits` |
| `app/parsing/normalization.py` | `app.agent.intake.normalization` |
| `app/parsing/parser.py` | `app.agent.intake.parser` |
| `app/parsing/prompts.py` | `app.agent.intake.prompts` |
| `app/parsing/rule_parser.py` | `app.agent.intake.rule_parser` |
| `app/parsing/validator.py` | `app.agent.intake.validator` |
| `app/prompts/models.py` | `app.agent.prompt_catalog.models` |
| `app/prompts/registry.py` | `app.agent.prompt_catalog.registry` |
| `app/prompts/renderer.py` | `app.agent.prompt_catalog.renderer` |
| `app/repositories/order_repository.py` | `app.tools.database.order_repository` |
| `app/repositories/queue_repository.py` | `app.tools.database.queue_repository` |
| `app/repositories/workshop_repository.py` | `app.tools.database.workshop_repository` |
| `app/responses/formatter.py` | `app.agent.responses.formatter` |
| `app/responses/templates.py` | `app.agent.responses.templates` |
| `app/workflows/checkpointer.py` | `app.agent.router.checkpointer` |
| `app/workflows/graph.py` | `app.agent.router.graph` |
| `app/workflows/state.py` | `app.agent.router.state` |
| `app/domain/allocator/allocator.py` | `app.tools.allocator.allocator` |
| `app/domain/allocator/planner.py` | `app.tools.allocator.planner` |
| `app/domain/allocator/scoring.py` | `app.tools.allocator.scoring` |
| `app/integrations/llm/deepseek_client.py` | `app.agent.providers.deepseek_client` |
| `app/integrations/llm/llm_client.py` | `app.agent.providers.llm_client` |
| `app/workflows/nodes/conversation.py` | `app.agent.router.nodes.conversation` |

例如解析链路为 `app.agent.parser → app.parsing.parser → app.agent.intake.parser`；分配链路为 `app.allocator.planner → app.domain.allocator.planner → app.tools.allocator.planner`。

当前运行和辅助程序中均没有找到调用方的兼容路径，优先评估这些：

- `app/agent/draft_edits.py`、`normalization.py`、`rule_parser.py`、`validator.py`。
- `app/parsing/normalization.py`、`rule_parser.py`、`validator.py`。
- `app/prompts/models.py`、`renderer.py`。
- `app/allocator/scoring.py`、`app/domain/allocator/scoring.py`。
- 上面单独列出的 `app/http/status.py`（不是这 43 个动态转发文件之一）。

清理其余转发文件前，需要先把调用方迁移到最终路径，并处理原有 import/CLI 兼容约定。`app/auth.py`、`app/setup.py`、`app/session_cli.py`、`app/lifecycle_cli.py` 是仍有文档或测试使用的命令行入口，不能因为没有普通 import 而归为死代码。

**7. 容易误删、实际仍在使用的部分**

| 文件 / 内容 | 实际使用依据 |
|---|---|
| `app/ui/legacy.html`、`app/ui/sessions.js` | `main.py` L56–57 注册 `/legacy`、`/sessions.js`；旧页面 L77 加载会话脚本；HTTP 测试检查脚本可访问。 |
| `app/server.py::make_server`、`LocalServer` | 当前 CLI、HTTP 测试及 `evaluation/verify_ui.py` 使用。 |
| `app/agent/providers/llm_client.py`、`deepseek_client.py` | 原 parser/CLI 链路仍实例化这些后端；现有 SDK、提示词和故障测试也使用。新模型目录并未让它们整体废弃。 |
| `app/agent/router/nodes/conversation.py` 的 `parse_request`、`edit_form`、`followup`、`validate` | `router/graph.py` L11–12 通过字符串和 `getattr` 注册节点；普通函数名扫描容易漏掉。 |
| `app/api/routes/` 中的路由函数 | 由 FastAPI 装饰器注册并经 HTTP 执行，不要求 Python 代码显式调用。 |
| `app/api/dependencies.py::require_admin` | 当前产品路由暂未接入，但 `tests/test_account_roles.py` L43 注册临时路由测试；属于已验证的预留权限守卫。 |
| `app/agent/providers/llm_client.py::__getattr__` | Python 模块属性兼容机制，用于旧常量导入，不是普通无调用函数。 |
| `app/db/migrations/001` 至 `007` | 当前及旧数据库初始化、升级按顺序读取；历史迁移不属于废弃代码。 |
| `harness/simulate.py`、`evaluation/simulator_adapter.py` | 当前模拟器比较、验收和适配器测试使用。 |
| `demos/`、`evaluation/` 其他脚本 | 多数具有独立命令行入口，历史用途也在文档中记录，不能仅凭不参与网页主链路认定废弃。 |

辅助档案：`tests/fixtures/R02.json`、`R03.json`、`R09.json`、`R25.json`、`R27.json` 和 `evaluation/r09_demo.json` 没有找到当前程序读取它们的入口，文档将它们作为 Week 4 历史档案保留。它们可以归档，但不是运行代码。`prompt_messages_v1.json`、`response_messages_v1.json` 是当前测试夹具，仍在读取。根目录 `xiaoyu_test.txt` 仅为一次 Git 推送测试说明，不参与运行。

**8. 验证结果及边界**

所有纳入排查的 Python 文件均已通过语法树解析；清单中的主要定义行号、43 个转发目标和报告内的本地文件链接已复核。前端现有 11 项控制器测试全部通过；单独运行 `test_tools.py` 的 3 项测试也全部通过，确认旧 CSV 查询工具仍有有效测试调用。

Python 全套回归未完成：第一轮遇到沙箱临时目录的 SQLite 打开/目录清理权限错误；改用工作区内隔离目录后，带函数调用跟踪的运行长时间未完成，已停止。没有把这轮运行标记为通过，也没有用未完成的调用计数证明某段代码不会执行。本轮未运行会重写历史评估报告的验收脚本。

当前清单的判断以实际调用入口和引用关系为主，没有使用“文件名字旧”或“未被首页引用”作为单独的废弃依据。静态引用核查仍可能遗漏仓库外部调用、手动入口或未声明的动态加载方式。
