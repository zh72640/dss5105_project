# Skill Development Standards

Follow `AGENTS.md`, the existing Agent–Skill–Tool architecture, and the project's skill-loading conventions. A **skill** defines a reusable task capability or workflow; it is not a replacement for an Agent, Tool, or Service.

## 1. Core Principles

Every skill MUST satisfy five principles:

1. **Single Responsibility — One skill, one coherent capability.** Cover one well-defined user task or a tightly related set of tasks. Split unrelated workflows into separate skills; reuse existing skills before creating new ones.
2. **Clear Boundaries — Define when and when not to use it.** State triggers, supported scenarios, exclusions, prerequisites, and dependencies. Avoid overlapping skills without clear routing rules.
3. **Structured Inputs and Outputs — Define explicit contracts.** Specify required/optional inputs, relevant formats or constraints, and expected output fields or structure. Validate essential inputs and distinguish confirmed results from missing or inferred information. Use JSON or a schema only when the consuming interface requires it.
4. **Explicit and Feasible Steps — Make the workflow executable.** Break the task into logically ordered steps, each with an objective, concrete action, applicable Tool, and expected result. Specify dependencies, decision branches, validation checks, and completion conditions where relevant. Every step must be possible with the project's available capabilities.
5. **Complete Failure Strategies — Define safe alternatives.** Cover missing or ambiguous inputs, empty/stale/conflicting data, unavailable Tools, permission failures, and partial execution. State whether to clarify, retry, fall back, stop, or report partial results. Never fabricate success or silently ignore a failed step.

## 2. Architecture and Responsibilities

- **Agent / LangGraph:** Owns intent routing, conversation/workflow state, and orchestration.
- **Skill:** Specifies task-specific instructions, step sequences, Tool selection rules, and output requirements.
- **Tool:** Exposes a bounded agent-callable operation; follow `tool_development.md`.
- **Service / Repository:** Owns business logic, persistence, and external integrations.

A skill MAY coordinate multiple registered Tools, but MUST NOT implement Tool handlers, SQL/database access, shared business algorithms, or global Agent routing. Not every Tool call needs a Skill. Keep workflow state in the existing LangGraph mechanism, not hidden in skill instructions.

## 3. Skill Structure and Instructions

Use the existing `skills/` directory, loader, and required metadata format. When the project uses `SKILL.md`, keep it as the concise entry point; place extensive references or examples in separate files only when needed.

Each skill MUST document:

- **Name and Trigger:** What capability it provides and when the Agent should select it.
- **Scope and Dependencies:** In-scope/out-of-scope requests, prerequisites, registered Tools, and permissions.
- **Input Contract:** Required and optional data, validation rules, and defaults if justified.
- **Step-by-Step Workflow:** Numbered actions; for each step define `Objective → Action/Tool → Expected Result`, plus applicable branches and checks.
- **Output Contract:** Required structure, success criteria, and evidence or provenance where needed.
- **Failure Handling:** Recovery, retry limits, stop conditions, and partial-result behavior.

Write actionable instructions rather than vague goals. Separate mandatory from optional steps. Reference Tool interfaces without duplicating their implementation. Do not prescribe internal reasoning or unnecessary micro-steps.

## 4. Development Constraints

1. Before editing, inspect related skills, registered Tools, routing rules, and existing tests; identify overlap and reusable components.
2. Keep skills in the established location; do not embed full skill workflows or Tool implementations in Agent files.
3. If a needed operation is missing, add it through the existing Tool/Service architecture, following `tool_development.md`.
4. Do not assume unavailable Tools, hidden state, unsupported background execution, or unverified data.
5. Make state-changing steps explicit; respect existing authorization, confirmation, and retry/idempotency safeguards.
6. Preserve existing skill selection, business behavior, and interfaces; avoid unrelated refactors. Plan major migrations before editing.

## 5. Testing and Completion

- **Selection:** Correctly trigger for in-scope requests and reject out-of-scope or overlapping cases.
- **Contracts:** Verify input validation, structured outputs, and missing-data behavior.
- **Workflow:** Test ordering, branches, Tool calls, validation, and completion conditions.
- **Failures:** Test Tool errors, permission issues, retry/stop rules, and partial results without false success.
- **Regression:** Run relevant unit/integration tests and verify existing Agent/Skill behavior remains intact.

A skill is complete only when its boundaries, contracts, steps, and failure paths are documented, executable with available Tools, and verified by relevant tests.