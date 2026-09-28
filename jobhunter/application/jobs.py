"""Browsing and deciding on jobs."""
from ..domain import stages
from ..domain.errors import InvalidInput, NotFound
from .context import AppContext
from .tracker import get_job, set_stage


def list_jobs(ctx: AppContext, page=1, page_size=50, **filters):
    rows, total = ctx.repos.jobs.list(limit=page_size, offset=(page - 1) * page_size, **filters)
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def detail(ctx: AppContext, job_id):
    r = ctx.repos
    job = get_job(ctx, job_id)
    cv = r.cvs.get(job["cv_id"]) if job["cv_id"] else None
    return {**job, "cv": {"id": cv["id"], "name": cv["name"]} if cv else None,
            "counts": r.jobs.counts(job_id), "next_reminder": r.reminders.next_for_job(job_id)}


def update(ctx: AppContext, job_id, stage=None, feedback=None, feedback_reason=None, notes=None, cv_id=None):
    r = ctx.repos
    get_job(ctx, job_id)
    fields = {}
    if feedback is not None:
        if feedback not in ("up", "down", "none"):
            raise InvalidInput("feedback must be up, down or none")
        fields["feedback"] = None if feedback == "none" else feedback
        fields["feedback_reason"] = None if feedback == "none" else feedback_reason
    if notes is not None:
        fields["notes"] = notes
    if cv_id is not None:
        if not r.cvs.get(cv_id):
            raise NotFound("CV not found")
        fields["cv_id"] = cv_id
    if fields:
        r.jobs.update(job_id, **fields)
    if stage:
        set_stage(ctx, job_id, stage)
        implicit = stages.implicit_feedback(stage)
        if feedback is None and implicit:
            r.jobs.update(job_id, feedback=implicit)
    return r.jobs.get(job_id)


def bulk_stage(ctx: AppContext, ids, stage):
    stages.validate_stage(stage)
    for jid in ids:
        set_stage(ctx, jid, stage)
    return {"updated": len(ids)}
