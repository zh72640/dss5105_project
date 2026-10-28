# Tool categories (1–4)

Locked conventions for Agent-callable tools. Docstrings on `@tool` always carry **purpose**, **Args**, **Returns**, and **Errors**. Lower layers for categories 1, 2, and 4 are **implementation only** (no Tool-style Args/Returns essays).

| Category | When | Tool body | Lower layer |
| --- | --- | --- | --- |
| 1 Allocator | Allocation math | Docs + `return allocator_fn(...)` | `app/allocator/` |
| 2 DB | Persistence / fact load | Docs + `return repo_fn(...)` (+ ToolFailure map) | `app/db/` |
| 3 Simple | Trivial, not reused elsewhere | Docs + **inline** implementation | None |
| 4 Service | Complex business beyond DB or allocator alone | Docs + **one** `return service_fn(...)` | `app/services/` named function |

Do not reintroduce `execute(name, args)` dispatch. One Tool maps to one forward target (or inline for category 3).

See also [tool_development.md](tool_development.md).
