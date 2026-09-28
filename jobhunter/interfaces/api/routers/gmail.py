from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ....application import mail
from ..auth import current_user
from ..deps import get_ctx

router = APIRouter(prefix="/gmail", tags=["gmail"])
authed = [Depends(current_user)]


def _web(request, path, **params):
    return f"{request.app.state.container.config.web_origin}{path}?{urlencode(params)}"


@router.get("/status", dependencies=authed)
def status(ctx=Depends(get_ctx)):
    return mail.status(ctx)


@router.get("/connect", dependencies=authed)
def connect(ctx=Depends(get_ctx)):
    return {"url": mail.connect_url(ctx)}


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             ctx=Depends(get_ctx)):
    """Google redirects the browser here without a bearer token, so this route is protected by
    the one-time OAuth `state` that /gmail/connect issued to the signed-in user."""
    if error or not code:
        return RedirectResponse(_web(request, "/settings", gmail="error", reason=error or "no_code"))
    try:
        email = mail.complete(ctx, code, state)
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(_web(request, "/settings", gmail="error", reason=str(e)[:200]))
    return RedirectResponse(_web(request, "/settings", gmail="connected", email=email))


@router.post("/disconnect", dependencies=authed)
def disconnect(ctx=Depends(get_ctx)):
    mail.disconnect(ctx)
    return {"ok": True}


@router.post("/sync", dependencies=authed)
def sync(ctx=Depends(get_ctx)):
    return {"replies": mail.sync_replies(ctx)}
