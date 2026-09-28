"""Dashboard read model."""
from ..domain import stages
from . import usage
from .context import AppContext


def stats(ctx: AppContext):
    r = ctx.repos
    counts = r.jobs.stage_counts()
    data = r.jobs.dashboard()
    return {**data, "stages": counts, "funnel": stages.funnel(counts),
            "reminders": [x for x in r.reminders.list()][:6],
            "replies": r.outreach.recent_replies(5),
            "activity": r.events.recent(12),
            "spend_month": usage.month_spend(ctx), "budget": usage.budget(ctx)}
