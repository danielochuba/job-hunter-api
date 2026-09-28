from fastapi import APIRouter, Depends

from ....application import dashboard, notifications, usage
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import ReadIn

router = APIRouter(tags=["misc"], dependencies=[Depends(current_user)])


@router.get("/stats")
def stats(ctx=Depends(get_ctx)):
    return dashboard.stats(ctx)


@router.get("/notifications")
def list_notifications(unread: bool = False, limit: int = 30, ctx=Depends(get_ctx)):
    return notifications.listing(ctx, unread, limit)


@router.post("/notifications/read")
def mark_read(body: ReadIn, ctx=Depends(get_ctx)):
    notifications.mark_read(ctx, body.ids)
    return {"ok": True}


@router.get("/usage")
def usage_report(month: str | None = None, ctx=Depends(get_ctx)):
    return usage.report(ctx, month)
