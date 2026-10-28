# Tool Development Standards

Follow `AGENTS.md`, the existing project architecture, and the installed LangChain/LangGraph versions. This document applies to **agent-callable tools**, not ordinary helper or Service functions.

Classify each Tool as category **1 Allocator**, **2 DB**, **3 Simple**, or **4 Service** — see [tool_categories.md](tool_categories.md). Put purpose/Args/Returns/Errors on the `@tool`. Categories 1/2/4 thin-forward to one lower function; category 3 implements inline.

## 1. Core Principles

Every tool MUST follow four principles:

1. **Single Purpose — One tool, one job.** Expose one clearly defined operation. Do not combine unrelated actions or embed an entire workflow in one tool.
2. **Clear Description — Tell the LLM when to use it.** Use an unambiguous name and concise docstring describing what the tool does, when to call it, required inputs, and relevant limitations.
3. **Type Hints — Define a reliable contract.** Type all parameters and return values. Use Pydantic `args_schema` when inputs need structured fields or additional validation; validate business constraints explicitly.
4. **Error Handling — Fail gracefully.** Handle expected invalid-input, not-found, permission, and dependency errors according to project conventions. Never hide failures, leak raw exceptions, or fabricate successful results.

## 2. Architecture and Responsibilities

Preferred flow: `Agent / Skill → Tool → Service (if needed) → Repository / Adapter`.

- **Agent / Skill:** Decides which operation to use and coordinates multi-step workflows.
- **Tool:** Provides a thin agent-callable interface: input validation, delegation, and consistent output.
- **Service:** Implements reusable business rules, complex operations, or transaction logic.
- **Repository / Adapter:** Manages database access and external integrations.

A simple tool may call an existing helper directly. Do not create a Service merely to add a layer. Keep SQL, persistence logic, complex algorithms, and orchestration out of tool handlers.

## 3. LangChain / LangGraph Conventions

1. Define agent-callable tools with the project's supported LangChain interfaces, preferably `@tool` (or `StructuredTool` when appropriate). Do not create a competing tool framework.
2. Place tool definitions in the established `tools/` directory; organize by domain and prefer descriptive `snake_case` verb-object names (e.g., `get_order_status`).
3. Provide clear docstrings and typed input schemas so the LLM can select tools and supply correct arguments. Keep descriptions accurate and distinguish overlapping tools.
4. Register tools through the existing mechanism and integrate with the current LangGraph execution path (e.g., `ToolNode` where already used). Keep graph routing and workflow state transitions in the orchestration layer.
5. Use framework-supported runtime/context injection when necessary; do not expose internal runtime parameters as LLM-provided business inputs.
6. Reuse existing tool contracts and registrations; do not rename or change interfaces without an explicit migration requirement.

## 4. Implementation Constraints

1. Delegate business logic to existing Services or helpers; do not duplicate logic across tools, Skills, and Agents.
2. Return concise, serializable results following established success/error conventions. Distinguish missing data from failed execution.
3. Catch and translate **expected** errors at appropriate boundaries; do not use blanket exception handlers that mask defects.
4. Make writes and side effects explicit. Enforce authorization, tenant isolation, required confirmation, and retry/idempotency safeguards when applicable.
5. Follow existing async, timeout, and logging conventions. Never expose secrets or sensitive internal details.
6. Avoid unrelated refactors, unnecessary dependencies, and additional architectural layers.

## 5. Development and Testing

**Before editing:** Inspect related tools, registration, Services, callers, and existing tests; identify reusable code and compatibility requirements.

**During implementation:** Add or update the smallest appropriate Tool, schema, lower-layer logic, and registration; preserve existing business behavior.

**Before completion:**
- Test valid and invalid inputs, empty results, expected failures, and output serialization.
- Verify LangChain tool invocation and LangGraph integration where relevant.
- For write tools, test authorization, side effects, and retry safety.
- Run project lint/type/test checks and confirm no functional regression.

A tool is complete only when its interface is clear, registration works, relevant tests pass, and architecture boundaries remain intact.