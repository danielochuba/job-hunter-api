from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from ....application import jobs, tracker
from ....application.importing import import_job
from ....domain.errors import InvalidInput
from ..auth import current_user
from ..deps import get_ctx, launch
from ..schemas import BulkStageIn, ImportIn, JobPatch, NoteIn

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(current_user)])


@router.get("")
def list_jobs(stage: str | None = None, min_fit: int | None = None, source: str | None = None,
              q: str | None = None, feedback: str | None = None, since: str | None = None, sort: str = "fit",
              page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), ctx=Depends(get_ctx)):
    return jobs.list_jobs(ctx, page=page, page_size=page_size, stage=stage, min_fit=min_fit, source=source, q=q,
                          feedback=feedback, since=since, sort=sort)


@router.get("/sources")
def sources(ctx=Depends(get_ctx)):
    return ctx.repos.jobs.sources()


@router.post("/bulk")
def bulk(body: BulkStageIn, ctx=Depends(get_ctx)):
    return jobs.bulk_stage(ctx, body.ids, body.stage)


@router.post("/import")
def import_(body: ImportIn, request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    if not (body.url or body.text):
        raise InvalidInput("Give a URL or paste the job description")
    return launch(request, ctx, background, "import", import_job, body.model_dump())


@router.get("/{job_id}")
def get_job(job_id: int, ctx=Depends(get_ctx)):
    return jobs.detail(ctx, job_id)


@router.patch("/{job_id}")
def patch_job(job_id: int, body: JobPatch, ctx=Depends(get_ctx)):
    return jobs.update(ctx, job_id, **body.model_dump())


@router.get("/{job_id}/events")
def events(job_id: int, ctx=Depends(get_ctx)):
    return ctx.repos.events.for_job(job_id)


@router.post("/{job_id}/events")
def add_note(job_id: int, body: NoteIn, ctx=Depends(get_ctx)):
    return tracker.add_note(ctx, job_id, body.note)


@router.get("/{job_id}/applications")
def applications(job_id: int, ctx=Depends(get_ctx)):
    return ctx.repos.applications.for_job(job_id)


@router.get("/{job_id}/prep")
def prep(job_id: int, ctx=Depends(get_ctx)):
    return ctx.repos.prep.latest(job_id)


@router.get("/{job_id}/contacts")
def contacts(job_id: int, ctx=Depends(get_ctx)):
    return ctx.repos.contacts.for_job(job_id)


@router.get("/{job_id}/outreach")
def outreach(job_id: int, ctx=Depends(get_ctx)):
    return ctx.repos.outreach.for_job(job_id)
