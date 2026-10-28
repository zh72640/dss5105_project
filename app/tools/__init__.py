"""Agent-callable Tool contracts.

See ``docs/tool_categories.md`` for categories 1–4. Registry holds Tool objects;
domain modules thin-forward to allocator, db, or services (or implement inline).
"""
from app.tools.registry import TOOLS, allowed_for_task, invoke_tool

__all__ = ["TOOLS", "allowed_for_task", "invoke_tool"]
