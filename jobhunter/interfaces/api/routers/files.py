"""LOCAL_MODE only: serves stored files (CVs, cover letters, avatars) from local disk."""
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(tags=["files"])


@router.get("/files/{path:path}")
def get_file(path: str, request: Request, download: str | None = None):
    data = request.app.state.container.storage.download(path)
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if media_type.startswith("text/"):
        media_type += "; charset=utf-8"
    # RFC 5987 form: download names can contain non-ASCII (e.g. accented company names).
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(download)}"} if download else None
    return Response(data, media_type=media_type, headers=headers)
