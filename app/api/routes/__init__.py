"""HTTP routers mounted by ``app.main.create_app`` under ``/api``.

Modules: system, auth, orders/events, desk, models, chat (Chat v2).
Legacy ``/api/sessions``, ``/api/requests``, and ``/api/jobs`` were retired.
"""
from fastapi import APIRouter
from . import auth, orders, desk, system, models, chat

router = APIRouter(prefix="/api")
for module in (system, auth, orders, desk, models, chat):
    router.include_router(module.router)
