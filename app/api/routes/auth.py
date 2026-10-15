import threading
import time
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from app.api.dependencies import Context, get_context, require_user
from app.api.errors import ApiError, ERROR_RESPONSES
from app.core import security
from app.schemas.api import LoginInput, EmptyInput, IdentityOutput, LoginOutput
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["Authentication"], responses=ERROR_RESPONSES)


class LoginLimiter:
    def __init__(self):
        self.lock, self.attempts = threading.Lock(), []

    def check(self):
        with self.lock:
            now = time.monotonic()
            self.attempts[:] = [t for t in self.attempts if now - t < 60]
            if len(self.attempts) >= 10:
                raise ApiError(429, "LOGIN_RATE_LIMIT", "Too many attempts. Try again in one minute.")
            self.attempts.append(now)


@router.get("/me", response_model=IdentityOutput)
def me(ctx: Context = Depends(get_context)):
    return service.auth_me(ctx.settings.db_path, ctx.username, require_auth=ctx.settings.require_auth)


@router.post("/login", response_model=LoginOutput)
def login(body: LoginInput, request: Request):
    request.app.state.login_limiter.check()
    token = service.login(request.app.state.settings.db_path, body.username, body.password)
    if not token:
        raise ApiError(401, "INVALID_CREDENTIALS")
    principal = service.identify_principal(request.app.state.settings.db_path, token)
    if not principal:
        raise ApiError(401, "INVALID_CREDENTIALS")
    response = JSONResponse(principal)
    response.set_cookie(security.COOKIE, token, max_age=security.TTL, httponly=True, samesite="Strict")
    return response


@router.post("/logout")
def logout(body: EmptyInput, ctx: Context = Depends(require_user)):
    service.logout(ctx.settings.db_path, ctx.token)
    response = JSONResponse({"success": True})
    response.set_cookie(security.COOKIE, "", max_age=0, httponly=True, samesite="Strict")
    return response
