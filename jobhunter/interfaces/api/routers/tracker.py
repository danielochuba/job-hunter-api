from fastapi import APIRouter, Depends

from ....application import tracker
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import ReminderIn, ReminderPatch

router = APIRouter(tags=["tracker"], dependencies=[Depends(current_user)])


@router.get("/tracker")
def board(ctx=Depends(get_ctx)):
    return tracker.board(ctx)


@router.get("/reminders")
def list_reminders(include_done: bool = False, ctx=Depends(get_ctx)):
    return ctx.repos.reminders.list(include_done)


@router.post("/reminders")
def add_reminder(body: ReminderIn, ctx=Depends(get_ctx)):
    return ctx.repos.reminders.create(**body.model_dump())


@router.patch("/reminders/{reminder_id}")
def patch_reminder(reminder_id: int, body: ReminderPatch, ctx=Depends(get_ctx)):
    return tracker.update_reminder(ctx, reminder_id, **body.model_dump(exclude_none=True))


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, ctx=Depends(get_ctx)):
    ctx.repos.reminders.delete(reminder_id)
    return {"ok": True}
