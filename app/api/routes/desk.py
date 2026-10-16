import json
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from app.api.dependencies import Context, require_user
from app.api.errors import ApiError, ERROR_RESPONSES
from app.schemas.api import ItemsOutput
from app.services.desk import service as desk

router = APIRouter(tags=["Desk and audit"], responses=ERROR_RESPONSES)


@router.get("/dashboard", response_model=dict)
def dashboard(ctx: Context = Depends(require_user)):
    return desk.dashboard(ctx.settings.db_path, ctx.settings.as_of)


@router.get("/workshops", response_model=ItemsOutput, response_model_exclude_unset=True)
def workshops(q: str = "", status: str = "", category: str = "", ctx: Context = Depends(require_user)):
    return desk.workshops(ctx.settings.db_path, ctx.settings.as_of, query=q.strip()[:200],
                          status=status, category=category)


@router.get("/audit", response_model=ItemsOutput, response_model_exclude_unset=True)
def audit(q: str = "", status: str = "", page: int = Query(1, ge=1, le=1000000),
          page_size: int = Query(25, ge=1, le=100), ctx: Context = Depends(require_user)):
    return desk.audit(ctx.settings.db_path, query=q.strip()[:200], status=status, page=page, page_size=page_size)


@router.get("/audit/export", response_class=Response,
            responses={200: {"content": {"text/csv": {}, "application/json": {}}}})
def export(format: str = "json", ctx: Context = Depends(require_user)):
    if format not in ("csv", "json"):
        raise ApiError(400, "INVALID_EXPORT_FORMAT")
    payload = desk.audit(ctx.settings.db_path, export=True)
    body = desk.audit_csv(payload["items"]) if format == "csv" else json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(body, media_type="text/csv" if format == "csv" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="sweaterco-allocation-history.{format}"'})


@router.get("/audit/{request_id}", response_model=dict)
def detail(request_id: str, ctx: Context = Depends(require_user)):
    items = desk.audit(ctx.settings.db_path, request_id=request_id)["items"]
    if not items:
        raise ApiError(404, "AUDIT_NOT_FOUND")
    return items[0]


@router.get("/history", response_model=list[dict])
def history(ctx: Context = Depends(require_user)):
    return desk.history(ctx.settings.db_path)
