"""LLM-drafted outreach emails. Drafts only: sending is a separate, explicit user action (mail.py)."""
from ..domain.cv import as_text, with_contact
from ..domain.errors import Conflict, InvalidInput, NotFound
from .context import AppContext
from .tracker import get_job
from .usage import metered_llm

EMAIL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["subject", "body"],
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
}

EMAIL_SYSTEM = """You write a short cold email from a job candidate to someone at a company about
one specific open role. Rules:
- 90-150 words, plain text, no markdown, no placeholders like [Name].
- Greet the recipient by first name if known, else "Hi there" (or the team, for generic inboxes).
- One sentence on why this role, then 1-2 concrete, relevant achievements taken ONLY from the CV
  (never invent numbers, employers or technologies), then a low-pressure ask (a short chat, or who
  the right person is). Mention the CV is attached if ATTACH_CV is yes.
- Subject: specific and under 70 characters, e.g. "Backend Engineer role – Python/Django, 3 yrs".
- End with the provided signature exactly, or the candidate's name if there is none."""

EDITABLE = {"to_email", "subject", "body", "attach_cv", "status"}


def draft(ctx: AppContext, job_id, contact_id=None, to_email=None):
    r = ctx.repos
    job = get_job(ctx, job_id)
    contact = r.contacts.get(contact_id) if contact_id else None
    to_email = to_email or (contact or {}).get("email")
    if not to_email:
        raise InvalidInput("Pick a contact or enter an email address.")
    user = r.users.get()
    app = r.applications.latest(job_id)
    cv_row = r.cvs.get((app or {}).get("cv_id") or job["cv_id"] or 0) or r.cvs.default()
    if not cv_row:
        raise InvalidInput("No CV available: upload one first.")
    cv = with_contact(cv_row["cv"], user)
    signature = (user or {}).get("email_signature") or (user or {}).get("full_name") or ""
    attach = bool(app and app["cv_pdf_path"])
    recipient = (f"{contact.get('name') or 'unknown name'} — {contact.get('role') or 'unknown role'} "
                 f"({contact['source']})" if contact else to_email)
    msg = (f"CANDIDATE CV:\n{as_text(cv)}\n\n---\nJOB: {job['title']} at {job['company']} ({job['location']})\n"
           f"{job['description'][:6000]}\n\nFIT SUMMARY: {(job['fit'] or {}).get('summary', '')}\n\n"
           f"COVER LETTER (for tone/material):\n{((app or {}).get('cover_letter') or '')[:3000]}\n\n"
           f"RECIPIENT: {recipient}\nATTACH_CV: {'yes' if attach else 'no'}\nSIGNATURE:\n{signature}")
    llm = metered_llm(ctx)
    res = llm.structured(llm.fast_model, EMAIL_SYSTEM, msg, EMAIL_SCHEMA, "outreach_email", purpose="outreach")
    return r.outreach.create(job_id=job_id, contact_id=contact_id, to_email=to_email, subject=res["subject"],
                             body=res["body"], attach_cv=attach)


def get(ctx: AppContext, outreach_id):
    o = ctx.repos.outreach.get(outreach_id)
    if not o:
        raise NotFound("Email not found")
    return o


def edit(ctx: AppContext, outreach_id, **fields):
    o = get(ctx, outreach_id)
    fields = {k: v for k, v in fields.items() if k in EDITABLE and v is not None}
    if fields.get("status") not in (None, "draft", "skipped"):
        raise InvalidInput("status can only be set to draft or skipped")
    if o["status"] in ("sent", "replied") and set(fields) - {"status"}:
        raise Conflict("This email has already been sent")
    return ctx.repos.outreach.update(outreach_id, **fields)


def delete(ctx: AppContext, outreach_id):
    if get(ctx, outreach_id)["status"] in ("sent", "replied"):
        raise Conflict("Sent emails are kept for the record")
    ctx.repos.outreach.delete(outreach_id)
