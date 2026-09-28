from fastapi import APIRouter, Depends

from ....application import contacts, mail, outreach
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import ContactIn, DraftIn, OutreachPatch

router = APIRouter(tags=["contacts"], dependencies=[Depends(current_user)])


@router.post("/contacts")
def add_contact(body: ContactIn, ctx=Depends(get_ctx)):
    return contacts.add_manual(ctx, body.job_id, body.email, body.name, body.role)


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, ctx=Depends(get_ctx)):
    ctx.repos.contacts.delete(contact_id)
    return {"ok": True}


@router.post("/outreach/draft")
def draft(body: DraftIn, ctx=Depends(get_ctx)):
    return outreach.draft(ctx, body.job_id, body.contact_id, body.to_email)


@router.put("/outreach/{outreach_id}")
def edit(outreach_id: int, body: OutreachPatch, ctx=Depends(get_ctx)):
    return outreach.edit(ctx, outreach_id, **body.model_dump())


@router.post("/outreach/{outreach_id}/send")
def send(outreach_id: int, ctx=Depends(get_ctx)):
    """Explicit user action only: the UI asks for confirmation before calling this."""
    return mail.send(ctx, outreach_id)


@router.delete("/outreach/{outreach_id}")
def delete(outreach_id: int, ctx=Depends(get_ctx)):
    outreach.delete(ctx, outreach_id)
    return {"ok": True}
