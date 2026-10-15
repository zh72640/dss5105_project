from fastapi import APIRouter, Depends
from app.api.dependencies import require_user, get_model_registry

router = APIRouter(tags=["Models"])


@router.get("/models", response_model=dict)
def models(ctx=Depends(require_user), registry=Depends(get_model_registry)):
    return registry.public()
