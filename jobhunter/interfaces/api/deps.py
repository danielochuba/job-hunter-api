import logging
import time
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Request

from ...application import runs

log = logging.getLogger("jobhunter.runs")
CONNECT_ATTEMPTS = 5


def get_container(request: Request):
    return request.app.state.container


def get_ctx(request: Request):
    """One pooled connection / repository bundle per request."""
    with request.app.state.container.pooled() as ctx:
        yield ctx


def _fail(container, run_id, error):
    """Last resort when the run's own connection can't be opened: record the failure via the pool,
    so the run doesn't sit in 'queued' forever (and block new runs of its kind)."""
    try:
        with container.pooled() as ctx:
            ctx.repos.runs.update(run_id, status="failed", error=error[:2000], finished_at=datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001
        log.exception("could not mark run #%s as failed", run_id)


def _execute(container, run_id, fn):
    # Background work gets its own connection (never the request's). Opening it is retried, since a
    # brief DNS/network blip here would otherwise leave the run stuck in 'queued'.
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            session = container.session()
            ctx = session.__enter__()
        except Exception as e:  # noqa: BLE001
            if attempt == CONNECT_ATTEMPTS:
                log.error("run #%s: couldn't connect to the database: %s", run_id, e)
                _fail(container, run_id, f"Couldn't connect to the database to start this run: {str(e).splitlines()[0]}")
                return
            log.warning("run #%s: database connect failed (%s), retrying [%d/%d]", run_id, str(e).splitlines()[0][:100],
                        attempt, CONNECT_ATTEMPTS)
            time.sleep(min(2 * attempt, 8))
            continue
        try:
            runs.execute(ctx, run_id, fn)
        finally:
            session.__exit__(None, None, None)
        return


def launch(request: Request, ctx, background: BackgroundTasks, kind, fn, params=None):
    """Create the run row now (so the UI gets an id to poll) and execute it after the response."""
    run_id = runs.create(ctx, kind, params or {})
    background.add_task(_execute, request.app.state.container, run_id, fn)
    return {"run_id": run_id}
