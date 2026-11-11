"""Authenticated manual order entry; comparison and commitment are separate."""
from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import Context, require_user
from app.api.errors import ApiError, business_responses
from app.schemas.order_intake import (
    OrderReviewInput, OrderReviewOutput, OrderDecisionInput, OrderDecisionOutput, OrderHistoryOutput,
)
from app.services import order_intake

router = APIRouter(prefix="/order-intake", tags=["Order registration"],
                   responses=business_responses(OrderDecisionOutput))


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except order_intake.OrderIntakeError as error:
        raise ApiError(error.status, error.code, str(error)) from error


@router.post("/reviews", response_model=OrderReviewOutput)
async def review(body: OrderReviewInput, request: Request, ctx: Context = Depends(require_user)):
    # Keep the original submitted spelling alongside validated, normalized facts.
    data = await request.json()
    return await run_in_threadpool(_call, order_intake.check, data,
                                   actor=ctx.username, db_path=ctx.settings.db_path)


@router.get("/reviews/{review_id}", response_model=OrderReviewOutput)
def resume(review_id: str, ctx: Context = Depends(require_user)):
    return _call(order_intake.get_review, review_id, actor=ctx.username, db_path=ctx.settings.db_path)


@router.post("/reviews/{review_id}/decision", response_model=OrderDecisionOutput)
def decision(review_id: str, body: OrderDecisionInput, response: Response, ctx: Context = Depends(require_user)):
    result, status = _call(order_intake.decide, review_id, body.model_dump(),
                           actor=ctx.username, db_path=ctx.settings.db_path)
    response.status_code = status
    return result


@router.get("/history", response_model=OrderHistoryOutput)
def history(order_id: str | None = Query(default=None, max_length=128),
            limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
            ctx: Context = Depends(require_user)):
    return _call(order_intake.history, actor=ctx.username, db_path=ctx.settings.db_path,
                 order_id=order_id, limit=limit, offset=offset)
