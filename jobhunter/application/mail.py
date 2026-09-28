"""Gmail use cases: connect (OAuth), send reviewed outreach, detect replies.
Credentials live only in the integrations table and never leave the API."""
import secrets
from datetime import datetime, timezone

from ..domain import stages
from ..domain.errors import Conflict, Forbidden, InvalidInput, NotConfigured
from .context import AppContext
from .notifications import notify
from .outreach import get as get_outreach
from .tracker import get_job, set_stage

PROVIDER = "gmail"


def status(ctx: AppContext):
    row = ctx.repos.integrations.get(PROVIDER)
    return {"configured": ctx.mailer.configured(), "connected": bool(row and row.get("token")),
            "email": (row or {}).get("email")}


def connect_url(ctx: AppContext):
    if not ctx.mailer.configured():
        raise NotConfigured("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the API .env first")
    state = secrets.token_urlsafe(24)
    ctx.repos.integrations.set_pending_state(PROVIDER, state)
    return ctx.mailer.auth_url(state)


def complete(ctx: AppContext, code, state):
    row = ctx.repos.integrations.get(PROVIDER)
    if not row or not state or not secrets.compare_digest(row.get("pending_state") or "", state):
        raise Forbidden("OAuth state mismatch: start the Gmail connection again from Settings.")
    token, email = ctx.mailer.exchange_code(code, state)
    ctx.repos.integrations.save_token(PROVIDER, token, email)
    return email


def disconnect(ctx: AppContext):
    ctx.repos.integrations.save_token(PROVIDER, None, None)


def _token(ctx: AppContext):
    row = ctx.repos.integrations.get(PROVIDER)
    if not row or not row.get("token"):
        raise NotConfigured("Gmail is not connected. Connect it in Settings.")
    return row["token"], row["email"]


def _save_token(ctx):
    return lambda token: ctx.repos.integrations.update_token(PROVIDER, token)


def send(ctx: AppContext, outreach_id):
    """Explicit user action only: the UI confirms before calling this."""
    r = ctx.repos
    o = get_outreach(ctx, outreach_id)
    if o["status"] in ("sent", "replied"):
        raise Conflict("Already sent.")
    if not o["subject"].strip() or not o["body"].strip():
        raise InvalidInput("Subject and body can't be empty.")
    token, sender = _token(ctx)
    user = r.users.get() or {}
    attachment = None
    app = r.applications.latest(o["job_id"])
    if o["attach_cv"] and app and app["cv_pdf_path"]:
        name = (user.get("full_name") or "CV").replace(" ", "_") + "_CV.pdf"
        attachment = (name, ctx.storage.download(app["cv_pdf_path"]), "application/pdf")
    from_header = f"{user.get('full_name')} <{sender}>" if user.get("full_name") else sender
    msg_id, thread_id = ctx.mailer.send(token, from_header, o["to_email"], o["subject"], o["body"], attachment,
                                        on_token=_save_token(ctx))
    row = r.outreach.update(outreach_id, status="sent", gmail_message_id=msg_id, gmail_thread_id=thread_id,
                            sent_at=datetime.now(timezone.utc))
    r.events.add(o["job_id"], "email_sent", f"Emailed {o['to_email']}: {o['subject']}")
    if get_job(ctx, o["job_id"])["stage"] in stages.PRE_APPLIED:
        set_stage(ctx, o["job_id"], "applied", "Applied via outreach email")
    return row


def is_reply(message, my_email, sent_at_ms):
    sender = (message.get("from") or "").lower()
    return bool(sender) and sender != (my_email or "").lower() and int(message.get("internal_ms", 0)) > sent_at_ms


def sync_replies(ctx: AppContext, log=print):
    st = status(ctx)
    if not st["connected"]:
        return 0
    token, me = _token(ctx)
    r = ctx.repos
    found = 0
    for o in r.outreach.awaiting_reply():
        messages = ctx.mailer.thread_messages(token, o["gmail_thread_id"], on_token=_save_token(ctx))
        sent_ms = int(o["sent_at"].timestamp() * 1000)
        replies = [m for m in messages if is_reply(m, me, sent_ms)]
        if not replies:
            continue
        first = replies[0]
        found += 1
        at = datetime.fromtimestamp(first["internal_ms"] / 1000, timezone.utc)
        r.outreach.update(o["id"], status="replied", replied_at=at, reply_snippet=first.get("snippet"))
        r.events.add(o["job_id"], "reply", f"Reply from {o['to_email']}: {(first.get('snippet') or '')[:200]}")
        r.reminders.close_auto(o["job_id"])
        job = get_job(ctx, o["job_id"])
        notify(ctx, "reply", f"Reply from {job['company']}", (first.get("snippet") or "")[:180], job_id=job["id"])
        log(f"Reply on #{o['job_id']} from {o['to_email']}")
    return found
