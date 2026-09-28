"""Run lifecycle for long tasks. The run row is updated as work progresses so the UI can poll it.
The same code path is used by the API (background tasks), the CLI and the scheduler."""
import traceback
from datetime import datetime, timezone

from ..domain.errors import RunBusy
from . import usage
from .context import AppContext

LLM_KINDS = {"match", "generate", "prep", "import", "daily", "ingest"}


class RunContext:
    """Handed to task functions: logging, progress, a metered LLM, and the app context."""

    def __init__(self, app: AppContext, run_id, echo=False):
        self.app = app
        self.id = run_id
        self.echo = echo
        self._llm = None

    @property
    def repos(self):
        return self.app.repos

    def log(self, msg):
        if self.echo:
            print(msg)
        self.repos.runs.append_log(self.id, str(msg)[:2000])

    def progress(self, done, total, label=None):
        p = {"done": done, "total": total}
        if label:
            p["label"] = label
        self.repos.runs.update(self.id, progress=p)

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self.app.llm_factory(usage.sink(self.app, self.id))
        return self._llm


def create(ctx: AppContext, kind, params=None, trigger="api"):
    busy = ctx.repos.runs.active_of_kind(kind)
    if busy:
        raise RunBusy(f"A {kind} run (#{busy['id']}) is already in progress")
    if kind in LLM_KINDS:
        usage.check_budget(ctx)
    return ctx.repos.runs.create(kind, params or {}, trigger)["id"]


def execute(ctx: AppContext, run_id, fn, echo=False):
    """Run `fn(run, params)` for an existing run row and record success/failure."""
    runs = ctx.repos.runs
    run = runs.update(run_id, status="running")
    rc = RunContext(ctx, run_id, echo=echo)
    try:
        result = fn(rc, run["params"] or {})
    except Exception as e:  # noqa: BLE001
        rc.log(traceback.format_exc(limit=5))
        runs.update(run_id, status="failed", error=str(e)[:2000], finished_at=datetime.now(timezone.utc))
        if echo:
            raise
        return None
    runs.update(run_id, status="succeeded", result=result if isinstance(result, dict) else None,
                finished_at=datetime.now(timezone.utc))
    return result


def run_now(ctx: AppContext, kind, fn, params=None, trigger="cli", echo=True):
    """Create + execute synchronously (CLI and scheduler)."""
    return execute(ctx, create(ctx, kind, params, trigger=trigger), fn, echo=echo)


def get(ctx: AppContext, run_id):
    from ..domain.errors import NotFound
    run = ctx.repos.runs.get(run_id)
    if not run:
        raise NotFound("Run not found")
    return {**run, "cost_usd": ctx.repos.usage.run_cost(run_id)}
