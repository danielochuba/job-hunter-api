from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ....application import runs
from ....application.tasks import TASKS
from ....domain.errors import InvalidInput
from ..auth import current_user
from ..deps import get_ctx, launch
from ..schemas import GenerateIn, JobIdIn, JobIdsIn, MatchIn

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(current_user)])


def _start(request, ctx, background, kind, params=None):
    return launch(request, ctx, background, kind, TASKS[kind], params)


@router.post("/collect")
def collect(request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    return _start(request, ctx, background, "collect")


@router.post("/match")
def match(body: MatchIn, request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    return _start(request, ctx, background, "match", body.model_dump(exclude_none=True))


@router.post("/daily")
def daily(request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    return _start(request, ctx, background, "daily")


@router.post("/generate")
def generate(body: GenerateIn, request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    if not body.job_ids and not body.top:
        raise InvalidInput("Pass job_ids or top")
    return _start(request, ctx, background, "generate", body.model_dump(exclude_none=True))


@router.post("/contacts")
def contacts(body: JobIdsIn, request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    return _start(request, ctx, background, "contacts", body.model_dump())


@router.post("/prep")
def prep(body: JobIdIn, request: Request, background: BackgroundTasks, ctx=Depends(get_ctx)):
    return _start(request, ctx, background, "prep", body.model_dump())


@router.get("")
def list_runs(limit: int = 30, kind: str | None = None, ctx=Depends(get_ctx)):
    return ctx.repos.runs.list(limit, kind)


@router.get("/active")
def active(ctx=Depends(get_ctx)):
    return ctx.repos.runs.active()


@router.get("/{run_id}")
def get_run(run_id: int, ctx=Depends(get_ctx)):
    return runs.get(ctx, run_id)
