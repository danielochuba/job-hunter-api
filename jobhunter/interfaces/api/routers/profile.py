from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile

from ....application import profile
from ..auth import current_user
from ..deps import get_ctx, launch
from ..schemas import CVIn, CVPatch

router = APIRouter(tags=["profile"], dependencies=[Depends(current_user)])


@router.get("/me")
def get_me(user=Depends(current_user), ctx=Depends(get_ctx)):
    return profile.get_me(ctx, user["id"])


@router.put("/me")
def put_me(body: dict[str, Any], user=Depends(current_user), ctx=Depends(get_ctx)):
    return profile.update_me(ctx, user["id"], body)


@router.post("/me/avatar")
async def avatar(file: UploadFile = File(...), user=Depends(current_user), ctx=Depends(get_ctx)):
    return profile.upload_avatar(ctx, user["id"], file.filename, file.content_type, await file.read())


@router.get("/cvs")
def list_cvs(ctx=Depends(get_ctx)):
    return profile.list_cvs(ctx)


@router.get("/cvs/{cv_id}")
def get_cv(cv_id: int, ctx=Depends(get_ctx)):
    return profile.get_cv(ctx, cv_id)


@router.post("/cvs")
def create_cv(body: CVIn, user=Depends(current_user), ctx=Depends(get_ctx)):
    return profile.create_cv(ctx, user["id"], **body.model_dump())


@router.put("/cvs/{cv_id}")
def update_cv(cv_id: int, body: CVPatch, ctx=Depends(get_ctx)):
    return profile.update_cv(ctx, cv_id, body.name, body.cv)


@router.delete("/cvs/{cv_id}")
def delete_cv(cv_id: int, ctx=Depends(get_ctx)):
    profile.delete_cv(ctx, cv_id)
    return {"ok": True}


@router.post("/cvs/{cv_id}/default")
def make_default(cv_id: int, ctx=Depends(get_ctx)):
    profile.make_default(ctx, cv_id)
    return {"ok": True}


@router.post("/cvs/{cv_id}/duplicate")
def duplicate(cv_id: int, user=Depends(current_user), ctx=Depends(get_ctx)):
    return profile.duplicate_cv(ctx, user["id"], cv_id)


@router.post("/cvs/upload")
async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                 ctx=Depends(get_ctx)):
    """Parse a CV file for review. Returns a run id; the parsed CV lands in the run's result."""
    data = await file.read()
    filename = file.filename or "cv.txt"
    path = profile.store_upload(ctx, filename, file.content_type, data)
    return launch(request, ctx, background, "ingest", profile.ingest_task(filename, data, path),
                  {"filename": filename})
