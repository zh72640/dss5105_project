from dataclasses import dataclass
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from app.core import security
from app.config.settings import Settings
from app.api.errors import ApiError

session_cookie = APIKeyCookie(name=security.COOKIE, auto_error=False,
                             description="Sign in through /api/auth/login; the browser sends this HttpOnly cookie.")


@dataclass(frozen=True)
class Context:
    settings: Settings
    username: str | None
    token: str
    role: str | None = None


def get_settings(request: Request):
    return request.app.state.settings


def get_model_registry(request: Request):
    return request.app.state.model_registry


def get_context(request: Request, settings: Settings = Depends(get_settings),
                cookie: str | None = Security(session_cookie)):
    token = cookie or ""
    principal = security.identify_principal(settings.db_path, token) if settings.require_auth else {
        "username": "local-demo", "role": "user"}
    return Context(settings, principal["username"] if principal else None, token,
                   principal["role"] if principal else None)


def require_user(ctx: Context = Depends(get_context)):
    if not ctx.username:
        raise ApiError(401, "LOGIN_REQUIRED")
    return ctx


def require_admin(ctx: Context = Depends(require_user)):
    if not ctx.settings.require_auth or ctx.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    return ctx
