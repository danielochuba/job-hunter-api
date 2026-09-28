from fastapi import BackgroundTasks, Request

from ...application import runs


def get_container(request: Request):
    return request.app.state.container


def get_ctx(request: Request):
    """One pooled connection / repository bundle per request."""
    with request.app.state.container.pooled() as ctx:
        yield ctx


def _execute(container, run_id, fn):
    # background work must not reuse the request's connection
    with container.session() as ctx:
        runs.execute(ctx, run_id, fn)


def launch(request: Request, ctx, background: BackgroundTasks, kind, fn, params=None):
    """Create the run row now (so the UI gets an id to poll) and execute it after the response."""
    run_id = runs.create(ctx, kind, params or {})
    background.add_task(_execute, request.app.state.container, run_id, fn)
    return {"run_id": run_id}
