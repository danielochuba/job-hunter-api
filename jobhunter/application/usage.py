"""LLM cost metering and the monthly budget guard."""
from datetime import datetime, timezone

from ..domain import pricing
from ..domain.errors import BudgetExceeded, InvalidInput
from .context import AppContext


def month_start(now=None):
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spend(ctx: AppContext):
    return ctx.repos.usage.spent_since(month_start())


def budget(ctx: AppContext):
    return float(ctx.repos.settings.get()["monthly_budget_usd"] or 0)


def check_budget(ctx: AppContext):
    spent, limit = month_spend(ctx), budget(ctx)
    if pricing.over_budget(spent, limit):
        raise BudgetExceeded(f"Monthly LLM budget reached (${spent:.2f} of ${limit:.2f}). "
                             "Raise it in Settings to continue.")


def sink(ctx: AppContext, run_id=None):
    def record(purpose, model, tin, tout):
        ctx.repos.usage.record(run_id, purpose, model, tin, tout, pricing.cost(model, tin, tout, ctx.prices))
    return record


def metered_llm(ctx: AppContext, run_id=None):
    """LLM for short synchronous calls (e.g. drafting one email); usage is still recorded."""
    check_budget(ctx)
    return ctx.llm_factory(sink(ctx, run_id))


def report(ctx: AppContext, month=None):
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise InvalidInput("month must be YYYY-MM") from e
    else:
        start = month_start()
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return {"month": start.strftime("%Y-%m"), **ctx.repos.usage.report(start, end), "budget": budget(ctx)}
