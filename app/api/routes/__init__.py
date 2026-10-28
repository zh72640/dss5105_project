"""HTTP routers mounted by ``app.main.create_app`` under ``/api``.

Modules: system (health/ai/models), auth, orders/events, desk, chat (Chat v2).
Legacy ``/api/sessions``, ``/api/requests``, and ``/api/jobs`` were retired.
"""
from fastapi import APIRouter
from . import auth, orders, desk, system, chat

router = APIRouter(prefix="/api")
for module in (system, auth, orders, desk, chat):
    router.include_router(module.router)
