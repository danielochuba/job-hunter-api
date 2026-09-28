"""Application tracking: stage changes, the timeline, reminders and the Kanban board."""
from datetime import datetime, timedelta, timezone

from ..domain import stages
from ..domain.errors import NotFound
from .context import AppContext


def get_job(ctx: AppContext, job_id):
    job = ctx.repos.jobs.get(job_id)
    if not job:
        raise NotFound(f"Job #{job_id} not found")
    return job


def set_stage(ctx: AppContext, job_id, stage, note=None):
    """Stage change + timeline event. Moving to `applied` schedules an automatic follow-up;
    closing stages cancel it."""
    stages.validate_stage(stage)
    job = get_job(ctx, job_id)
    if job["stage"] == stage:
        return job
    r = ctx.repos
    previous = job["stage"]
    job = r.jobs.update(job_id, stage=stage)
    r.events.add(job_id, "stage_change", note or f"{stages.label(previous)} → {stages.label(stage)}")
    if stage == "applied" and not r.reminders.has_open_auto(job_id):
        days = r.settings.get()["followup_days"]
        r.reminders.create(job_id=job_id, auto=True, due_at=datetime.now(timezone.utc) + timedelta(days=days),
                           note=f"Follow up with {job['company']} about {job['title']}")
    if stage in stages.CLOSES_FOLLOWUPS:
        r.reminders.close_auto(job_id)
    return job


def board(ctx: AppContext):
    rows = ctx.repos.jobs.board(stages.TRACKER_BOARD)
    columns = {s: [] for s in stages.TRACKER_BOARD}
    for row in rows:
        columns[row["stage"]].append(row)
    return {"columns": [{"stage": s, "jobs": columns[s]} for s in stages.TRACKER_BOARD]}


def add_note(ctx: AppContext, job_id, note):
    get_job(ctx, job_id)
    return ctx.repos.events.add(job_id, "note", note)


def update_reminder(ctx: AppContext, reminder_id, **fields):
    if "due_at" in fields:
        fields["notified"] = False
    row = ctx.repos.reminders.update(reminder_id, **fields)
    if not row:
        raise NotFound("Reminder not found")
    if fields.get("done") and row["job_id"]:
        ctx.repos.events.add(row["job_id"], "reminder_done", row["note"])
    return row
