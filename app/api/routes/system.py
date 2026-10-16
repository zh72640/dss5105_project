from fastapi import APIRouter, Depends
from app import APP_VERSION
from app.api.dependencies import Context, get_settings, require_user, get_model_registry
from app.config.settings import Settings
from app.schemas.api import HealthOutput
from app.services.dispatch import PIPELINE_VERSION

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthOutput)
def health(settings: Settings = Depends(get_settings), registry=Depends(get_model_registry)):
    return {"status": "ok", "backend": registry.settings.default_mode, "as_of_date": settings.as_of.isoformat(),
            "version": APP_VERSION, "pipeline_version": PIPELINE_VERSION}


@router.get("/ai/status", response_model=dict)
def ai_status(ctx: Context = Depends(require_user), registry=Depends(get_model_registry)):
    mode = registry.settings.default_mode
    spec = registry.resolve(require_model=False)
    return {"backend": mode, "configured": mode == "offline" or bool(spec and spec.configured),
            "model": spec.api_model_id if spec else "rules_v1" if mode == "offline" else None}


@router.get("/models", response_model=dict, tags=["Models"])
def models(ctx=Depends(require_user), registry=Depends(get_model_registry)):
    return registry.public()
