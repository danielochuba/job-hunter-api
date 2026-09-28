from fastapi import APIRouter, Depends

from ....application import generation
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import AppEdit, PreviewIn

router = APIRouter(prefix="/applications", tags=["applications"], dependencies=[Depends(current_user)])


@router.get("/{app_id}")
def get_application(app_id: int, ctx=Depends(get_ctx)):
    return generation.get_application(ctx, app_id)


@router.put("/{app_id}")
def edit(app_id: int, body: AppEdit, ctx=Depends(get_ctx)):
    """Saves edits as a new version (re-validated against the CV and re-rendered)."""
    return generation.save_edit(ctx, app_id, body.result, body.cover_letter)


@router.get("/{app_id}/files")
def files(app_id: int, ctx=Depends(get_ctx)):
    return generation.files(ctx, app_id)


@router.get("/{app_id}/html")
def html(app_id: int, ctx=Depends(get_ctx)):
    return generation.html(ctx, app_id)


@router.post("/{app_id}/preview")
def preview(app_id: int, body: PreviewIn, ctx=Depends(get_ctx)):
    return generation.preview(ctx, app_id, body.result)
