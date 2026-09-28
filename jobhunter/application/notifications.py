"""Notifications: always stored (the web app's bell), plus an OS toast since the API runs locally."""
from .context import AppContext


def notify(ctx: AppContext, kind, title, body="", job_id=None, toast=True):
    row = ctx.repos.notifications.create(kind, title, body, job_id)
    if toast and ctx.desktop_notifications:
        ctx.notifier.desktop(title, body)
    return row


def due_reminders(ctx: AppContext):
    """Notify once for each reminder that has come due."""
    rows = ctx.repos.reminders.due_unnotified()
    for r in rows:
        notify(ctx, "reminder", "Reminder" + (f": {r['company']}" if r.get("company") else ""), r["note"],
               job_id=r["job_id"])
        ctx.repos.reminders.mark_notified(r["id"])
    return len(rows)


def listing(ctx: AppContext, unread=False, limit=30):
    n = ctx.repos.notifications
    return {"items": n.list(unread, limit), "unread": n.unread_count()}


def mark_read(ctx: AppContext, ids=None):
    ctx.repos.notifications.mark_read(ids)
