# Tool 显式化与实现归属整理 Plan

目标是让开发者打开 `app/tools/`，就能直接看到每个 Tool 的名称、用途、输入、输出和实现方式。**状态：已按本计划实施（2026-10-16）。**

## 1. 目标与约束

当前共 12 个 Tool，全部迁为 `app/tools/` 下的显式 `@tool` 函数。相关 Tool 可以放在同一个 Python 文件中。

每个 Tool 必须具备：

- 明确的函数名称和 `@tool` 装饰器。
- 英文 Description，说明用途、调用时机和限制。
- 显式的输入参数、类型和必要校验。
- 明确的输出说明及返回类型。
- 可直接阅读的功能实现或下层函数调用。
- 必要的预期错误处理。

功能实现遵循以下规则：

| 功能类型 | 实现位置 |
| --- | --- |
| Allocation 算法相关 | 调用 `app/allocator/` 的函数 |
| 与算法无关的简单逻辑 | Tool 内直接实现，可复用已有普通辅助函数 |
| 数据库交互 | 调用 `app/db/` 的函数 |
| 复杂业务逻辑 | 调用 `app/services/` 的具名函数 |

保留现有 Tool 名称、业务参数和外部结果语义。此次不改变算法、Skill 工作流、HTTP API、数据库结构或推荐确认方式。

## 2. 当前问题与迁移方向

| 当前实现 | 调整方向 |
| --- | --- |
| `registry.py` 用字典集中描述 Tool | 改为登记真实的 `@tool` 对象，描述和输入 Schema 来自 Tool 本身 |
| `operations.py` 动态生成参数模型和 `StructuredTool` | 由显式函数签名或 `args_schema` 定义输入，删除动态生成逻辑 |
| `agent_operations.execute(name, args)` 集中实现 10 个 Tool | 简单逻辑迁入对应 Tool；复杂逻辑提取成普通具名 Service 函数 |
| `load_skill` 的 Tool 定义和执行实现位于 Agent | Tool 定义迁入 `app/tools/`，复用现有 Skill Loader |
| `record_production_event` 通过普通 `execute()` 函数实现 | 改为显式 `@tool` 函数，继续调用 Lifecycle Service |
| Tool 参数同时经过自定义字典校验和生成的 Pydantic 校验 | 以 Tool 的原生输入 Schema 为校验依据，保留项目错误码映射 |

不能只给现有集中分派函数套上 `@tool`。每个函数内部应能看出它实际调用的 DB、Allocator 或 Service 能力。

## 3. 目标目录

```text
app/tools/
  __init__.py          只导出必要公开接口
  registry.py          登记 Tool 对象、任务权限与查询
  orders.py            get_order
  workshops.py         list_workshops、get_queue、score_workshop
  allocation.py        compute_plan
  requirements.py      update_constraints、check_requirements
  recommendations.py   save_recommendation、inspect_recommendation
  conversation.py      ask_user、load_skill
  production.py        record_production_event

app/schemas/tool.py     现有 ToolFailure；必要的具名输入/输出契约
```

简单输入优先通过函数签名定义；需要条件校验或复杂结构时使用显式 Pydantic `args_schema`。不为每个简单 Tool 强制新增一个 Schema 类。

不新增 Tool Factory、Manager、Dispatcher 或结果包装类。

## 4. 全部 Tool 的目标实现

| 文件与 Tool | Description / 功能 | Input | Output | 实现方式 |
| --- | --- | --- | --- | --- |
| `orders.py::get_order` | 获取登记订单及当前状态 | `order_id` | 订单字段、版本、剩余件数 | 调用 `order_repository.get_order()`；Tool 计算剩余件数并处理不存在 |
| `workshops.py::list_workshops` | 查询工坊资料及当前队列 | 可选 `workshop_id` | 工坊列表 | 调用 `workshop_repository.get_all()`；Tool 做简单筛选和序列化 |
| `workshops.py::get_queue` | 获取指定工坊在业务日期的队列 | `workshop_id` | 工坊 ID、队列天数、业务日期 | 调用 DB 函数取得已按业务日期折算的队列；不重复实现队列折算 |
| `workshops.py::score_workshop` | 计算指定订单在单工坊的指标与资格 | `workshop_id`、`order_id`、可选 `pieces` | ETA、lateness、defect、原始 hybrid、资格原因 | DB 取数后调用 Allocator 的现有评分和资格函数 |
| `allocation.py::compute_plan` | 计算当前任务的完整分配方案 | 无业务参数，使用可信上下文中的任务 | 方案、检查报告、事实及方案 hash、任务版本 | Service 准备输入，Tool 显式调用 `allocator.allocate()`，Service 完成结果核验 |
| `requirements.py::update_constraints` | 修改一项有用户依据的需求 | `field`、可选 `value`、`operation` | 草稿、任务版本、状态、旧推荐失效标志 | 调用具名 Service 函数，复用解释校验、约束补丁和持久化 |
| `requirements.py::check_requirements` | 检查需求与业务事实是否允许计算 | 无业务参数 | 状态、检查报告、事实 hash | 调用具名 Service 函数，复用 preflight 和任务状态更新 |
| `recommendations.py::save_recommendation` | 保存本次运行计算出的推荐预览 | 无业务参数 | 推荐 ID、任务版本、状态、结果 | 调用具名 Service 函数，重新核对事实、方案和版本后保存 |
| `recommendations.py::inspect_recommendation` | 获取当前推荐并核对有效性 | 无业务参数 | 当前会话最新推荐 | 调用具名 Service 函数，复用有效性核对和 DB 查询 |
| `production.py::record_production_event` | 执行明确请求的生产事件 | 保留现有 action、订单、版本、原因和动作相关参数 | 生命周期执行结果或拒绝原因 | Tool 保留调用授权校验，调用 `lifecycle.process_event()` |
| `conversation.py::ask_user` | 提出明确问题，等待用户补充 | `question` | 问题文本 | Tool 内校验并返回；Runtime 负责暂停本轮和后续恢复 |
| `conversation.py::load_skill` | 加载具名 Skill 的内容和元数据 | `name` | 名称、说明、正文、Tool 列表、hash | Tool 复用现有 Skill Loader；Runtime 负责已加载状态、权限和快照 |

### `compute_plan` 的复用安排

为满足 Tool 内显式调用 Allocator，同时避免复制推荐编排，将现有 `allocation.recommend()` 中的准备和结果处理提取为可复用函数，例如：

```text
prepare_recommendation()
  → preflight、取得快照、构造 AllocationRequest

allocator.allocate()
  → 完整分配计算

finish_recommendation()
  → check_solution、trace、facts_hash / plan_hash
```

新的 `compute_plan` 明确展示这三个步骤。原 `allocation.recommend()` 继续组合相同函数，供 Offline、推荐保存和确认复核使用。

任务状态限制、计算失败后的阻塞状态和旧推荐失效仍由 Service 处理。Allocator 内不增加会话或持久化职责。

## 5. 每个 Tool 的代码形式

示意：

```python
@tool
def get_order(order_id: str, config: RunnableConfig) -> dict:
    """Read a registered order and its current production state.

    Args:
        order_id: Exact registered order identifier.

    Returns:
        Registered order fields, version, state, and remaining pieces.

    Raises:
        ToolFailure: If the order does not exist.
    """
    connection = config["configurable"]["connection"]
    order = order_repository.get_order(connection, order_id)

    if order is None:
        raise ToolFailure(
            "ORDER_NOT_FOUND",
            "No registered order has that ID.",
        )

    return {
        **order,
        "remaining_pieces": order["pieces"] - order["completed_pieces"],
    }
```

实际实现还需通过参数注解或 `args_schema` 表达非空字符串、整数范围、枚举及额外字段限制。

Description、输入签名和返回说明直接位于函数附近。输入契约由 LangChain/Pydantic 生成；输出使用返回类型、Docstring 和必要的数据契约说明，不引入自定义装饰器。

## 6. 注册、上下文与 Runtime 接入

### Registry

`registry.py` 显式导入并登记 12 个 Tool 对象：

```python
TOOLS = {
    registered_tool.name: registered_tool
    for registered_tool in (
        get_order,
        list_workshops,
        get_queue,
        score_workshop,
        compute_plan,
        update_constraints,
        check_requirements,
        save_recommendation,
        inspect_recommendation,
        record_production_event,
        ask_user,
        load_skill,
    )
}
```

Registry 继续承担名称查找和必要的任务权限规则。删除手写 Provider Tool Schema 和按名称执行具体业务的分派。

### 隐藏上下文

当前安装的 LangChain 支持 `@tool` 及 `RunnableConfig` 注入。本次沿用现有执行循环，通过原生接口调用：

```text
选定 Tool
  → tool.invoke(arguments, config=本次调用的可信配置)
```

以下信息由 Runtime 提供，不进入模型可填写的参数：

- 数据库连接和会话快照。
- owner、业务日期。
- request ID、原生 Tool Call ID。
- 当前 plan。
- 用户消息及必要的 Skill 快照信息。

数据库连接只在当次调用及原有事务范围内使用，不保存进 checkpoint，不写入审计参数，也不保存在全局 Tool 对象中。

### Runtime 保留的职责

`agent/dynamic.py` 继续负责：

- 根据 Skill、任务类型和状态选择可见 Tool。
- 独立检查调用权限。
- 管理事务及 Tool 审计。
- 使用 `<request_id>:<native_tool_call_id>` 重放。
- 更新 loaded skills、plan 和 pending question。
- 构造原生 `ToolMessage`。
- 执行调用上限与 Completion Guard。

Tool 的定义和功能实现迁入 `app/tools/`；Graph 状态更新继续由 Runtime 处理。本次无需同时更换整个执行循环或引入 `ToolNode`。

保留现有对模型及审计的 `ok/data/error` 语义。生产事件拒绝时已有的业务结果数据也需保留，避免重复封装。

## 7. 文件级迁移与删除安排

| 文件 | 修改安排 |
| --- | --- |
| `app/tools/orders.py` | 新增显式 `get_order` |
| `app/tools/workshops.py` | 新增三个查询和评分 Tool |
| `app/tools/allocation.py` | 新增显式 `compute_plan`，调用 Allocator |
| `app/tools/requirements.py` | 新增两个需求管理 Tool |
| `app/tools/recommendations.py` | 新增推荐保存和检查 Tool |
| `app/tools/conversation.py` | 新增 `ask_user`、`load_skill` |
| `app/tools/production.py` | 将现有执行函数迁为显式 `@tool`，保留授权和生命周期调用 |
| `app/tools/registry.py` | 改为登记 Tool 对象；保留必要权限规则 |
| `app/tools/operations.py` | 所有调用迁移后删除动态 Schema、绑定工厂和重复执行入口；无剩余职责时删除文件 |
| `app/services/agent_operations.py` | 查询、评分和简单逻辑迁出；复杂分支提取为具名函数，最终删除 `execute(name, args)` |
| `app/services/allocation.py` | 提取可复用的输入准备和结果核验函数，保留 `recommend()` 现有调用契约 |
| `app/agent/dynamic.py` | 使用 Registry 中的 Tool 对象；删除 `LOAD_SKILL` 字典及内嵌 Skill 加载实现 |
| `app/agent/allocation_graph.py` | 调整 Registry 对象引用，保留固定 Skill 加载流程 |
| `app/schemas/tool.py` | 保留 `ToolFailure`，按需添加明确输入/输出契约 |
| 相关测试与文档 | 更新导入、Schema 检查、调用方式和模块职责说明 |

Service 文件本轮只做必要的函数提取，不全面重排目录。不得保留“每个 `@tool` 最终仍调用同一个 `execute(name, args)`”的结构。

## 8. 分阶段实施

1. **锁定工作区与契约基线。** 当前 Allocator 及调用方存在未提交修改；实施前核对其最新内容，记录 Tool 名称、参数、默认值、错误码、输出和状态变化。
2. **建立显式 Tool 与 Registry。** 先迁移查询、评分和 `ask_user`，验证原生参数 Schema、隐藏上下文及错误映射。
3. **迁移需求和推荐能力。** 提取具名 Service 函数，迁移 `update_constraints`、`check_requirements`、`compute_plan`、`save_recommendation`、`inspect_recommendation`。
4. **迁移 Skill 与生产 Tool。** 保留 Skill 快照及权限规则、生产事件稳定 ID、Lifecycle 事务和恢复行为。
5. **切换 Runtime 并清理。** 所有调用通过真实 Tool 对象执行后，删除旧动态工厂、集中分派及重复 Schema。
6. **完成回归和文档更新。** 按下述验收标准检查，交付修改文件和测试结果。

## 9. 验收标准

### 可读性与结构

- 12 个 Tool 都在 `app/tools/` 中有明确的 `@tool` 函数。
- 每个 Tool 都能直接找到 Description、Input、Output 和实现调用。
- Registry 名称唯一，全部 Skill 引用都能解析。
- Agent 内不再定义业务 Tool 或另藏 `load_skill` 实现。
- Tool 中无 SQL、分配公式或生产状态算法。
- 不再动态生成一组匿名 Tool，也不依赖集中式业务分派。

### 输入与调用

- 必填、可选、默认值、枚举、整数范围及额外参数行为符合现有契约。
- 不因 Pydantic 类型转换而接受原先应拒绝的非法值。
- owner、连接、消息证据、plan 和调用标识不出现在模型输入 Schema。
- 直接调用 `tool.invoke()` 与 Agent 内调用均可验证。
- 同一 Tool 对象用于不同会话时，不共享连接、权限或任务状态。

### 业务与恢复

- 查询、评分、推荐和生产结果保持原有语义。
- `inspect_recommendation` 的失效处理、计算失败的阻塞处理不丢失。
- 需求修改继续使旧推荐和当前 plan 失效。
- 保存推荐继续要求本次有效 plan，并复核最新事实和版本。
- 推荐不提交生产分配；显式确认仍走原 Chat 操作。
- 默认单工坊及明确授权的拆单沿用当前规则。
- `ask_user` 后停止本轮后续调用，下一条消息正确续接。
- 新旧 checkpoint 恢复时保持 Tool Call ID、Skill 快照及幂等行为。
- 推荐保存和生产事件在中断重试后不会重复生效。

使用 Mock 模型、内存或临时数据库运行 Tool、动态 Agent、架构对齐、Chat、Allocator 和 Lifecycle 相关回归，再执行完整 Python 与必要的前端回归。

本轮已核对本地 LangChain API 支持情况；未修改代码，未运行本次迁移的回归测试。
