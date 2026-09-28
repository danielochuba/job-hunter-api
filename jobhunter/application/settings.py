"""Settings (filters, queries, thresholds, schedule, budget) and tracked companies."""
from ..domain.errors import InvalidInput, NotFound
from ..domain.jobs import company_domain_from_url
from .context import AppContext

SETTINGS_FIELDS = {"filters", "search_queries", "aggregators", "matching", "schedule", "followup_days",
                   "monthly_budget_usd"}
MERGED_OBJECTS = ("filters", "matching", "schedule")


def get(ctx: AppContext):
    s = dict(ctx.repos.settings.get())
    s["available_aggregators"] = list(ctx.sources.aggregators)
    s["available_sources"] = list(ctx.sources.company_sources)
    s["next_daily_run"] = ctx.scheduler.next_run() if ctx.scheduler else None
    return s


def _check_time(t):
    h, _, m = (t or "").partition(":")
    if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
        raise InvalidInput("schedule.time must be HH:MM")


def update(ctx: AppContext, body):
    fields = {k: v for k, v in body.items() if k in SETTINGS_FIELDS}
    current = ctx.repos.settings.get()
    for k in MERGED_OBJECTS:  # partial JSON objects are merged
        if k in fields:
            fields[k] = {**(current[k] or {}), **(fields[k] or {})}
    if "schedule" in fields:
        _check_time(fields["schedule"].get("time", "07:30"))
    if "aggregators" in fields:
        unknown = set(fields["aggregators"]) - set(ctx.sources.aggregators)
        if unknown:
            raise InvalidInput(f"Unknown aggregators: {', '.join(sorted(unknown))}")
    if fields.get("followup_days") is not None and int(fields["followup_days"]) < 1:
        raise InvalidInput("followup_days must be at least 1")
    ctx.repos.settings.update(**fields)
    if "schedule" in fields and ctx.scheduler:
        ctx.scheduler.reschedule()
    return get(ctx)


# ---------------------------------------------------------------- companies

def detect(ctx: AppContext, url):
    found = ctx.sources.detect(url.strip())
    if not found:
        raise NotFound("Couldn't find a supported job board (Greenhouse, Lever, Ashby, Workable, "
                       "SmartRecruiters, Recruitee) on that page.")
    return {"source": found[0], "token": found[1]}


def add_company(ctx: AppContext, url=None, source=None, token=None, name=None, domain=None):
    if url and not (source and token):
        d = detect(ctx, url)
        source, token = d["source"], d["token"]
    if source not in ctx.sources.company_sources or not token:
        raise InvalidInput(f"source must be one of {', '.join(ctx.sources.company_sources)} and token is required")
    domain = domain or (company_domain_from_url(url) if url else None)
    return ctx.repos.companies.upsert(source, token.strip(), name or token, domain)


def update_company(ctx: AppContext, company_id, fields):
    row = ctx.repos.companies.update(company_id, **{k: v for k, v in fields.items()
                                                    if k in ("name", "domain", "active")})
    if not row:
        raise NotFound("Company not found")
    return row
