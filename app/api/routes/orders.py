from fastapi import APIRouter, Depends, Response
from app.api.dependencies import Context, require_user
from app.api.errors import ApiError, business_responses
from app.schemas.api import EventInput, DispatchOutput, OrderOutput
from app.services.production import lifecycle

router = APIRouter(tags=["Production"], responses=business_responses(DispatchOutput))


@router.get("/orders/{order_id}", response_model=OrderOutput, response_model_exclude_unset=True)
def inspect(order_id: str, ctx: Context = Depends(require_user)):
    order = lifecycle.inspect_order(order_id, db_path=ctx.settings.db_path)
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND")
    return order


@router.post("/events", response_model=DispatchOutput, response_model_exclude_unset=True,
             summary="Record completion, cancellation, lapse or reassignment")
def event(body: EventInput, response: Response, ctx: Context = Depends(require_user)):
    data = body.model_dump(exclude_unset=True)
    if ctx.settings.require_auth:
        data["actor"] = ctx.username
    payload = lifecycle.process_event(**data, db_path=ctx.settings.db_path, as_of=ctx.settings.as_of)
    codes = payload["result"]["reason_codes"]
    status = (400 if "INVALID_ARGUMENT" in codes else 404 if "ORDER_NOT_FOUND" in codes else
              503 if payload["result"]["decision_status"] == "ERROR" else
              409 if not payload["result"]["success"] else 200)
    if "IDEMPOTENCY_CONFLICT" in codes:
        status = 409
    response.status_code = status
    return payload
