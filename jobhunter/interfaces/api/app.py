"""FastAPI driver. Thin: routers translate HTTP <-> use cases; errors map by type."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ...domain import errors
from .auth import TokenVerifier
from .routers import (applications, contacts, gmail, health, insights, jobs, misc, profile, runs, settings,
                      tracker)

log = logging.getLogger("jobhunter.api")

STATUS = [(errors.NotFound, 404), (errors.InvalidInput, 422), (errors.RunBusy, 409), (errors.Conflict, 409),
          (errors.BudgetExceeded, 402), (errors.NotConfigured, 409), (errors.Unauthorized, 401),
          (errors.Forbidden, 403), (errors.ExternalServiceError, 502)]


STARTUP_ATTEMPTS = 6  # ~30s of retries: rides out brief DNS / network blips


def _startup_error(e):
    from psycopg.errors import UndefinedTable
    first = str(e).splitlines()[0]
    if isinstance(e, UndefinedTable):
        return False, (f"Connected, but the JobHunter tables don't exist yet: {first}\n"
                       "  Apply the schema: npx supabase link --project-ref <ref> && npx supabase db push")
    if "resolve host" in first or "getaddrinfo" in first or "timeout" in first.lower():
        return True, (f"Network problem reaching the database: {first}\n"
                      "  DATABASE_URL looks fine; this is DNS/connectivity. Check your internet, or try "
                      "`ipconfig /flushdns` / a different DNS server (1.1.1.1 or 8.8.8.8).")
    if "password authentication failed" in first or "tenant/user" in first:
        return False, f"Database rejected the login: {first}\n  Recopy DATABASE_URL from Supabase > Connect > Session pooler."
    return True, f"Can't reach the database: {first}\n  Check DATABASE_URL (Supabase > Connect > Session pooler)."


async def _check_database(container):
    """Mark interrupted runs, retrying transient failures; fail with one clear message otherwise."""
    import asyncio
    for attempt in range(1, STARTUP_ATTEMPTS + 1):
        try:
            with container.session() as ctx:
                ctx.repos.runs.mark_interrupted()
            if attempt > 1:
                log.info("Database reachable (attempt %d).", attempt)
            return
        except Exception as e:  # noqa: BLE001
            transient, msg = _startup_error(e)
            if not transient or attempt == STARTUP_ATTEMPTS:
                log.error(msg)
                raise RuntimeError(msg) from None
            wait = min(2 * attempt, 8)
            log.warning("Database not reachable yet (%s). Retrying in %ds [%d/%d]...",
                        str(e).splitlines()[0][:120], wait, attempt, STARTUP_ATTEMPTS)
            await asyncio.sleep(wait)


def create_app(container=None, start_background=True):
    if container is None:
        from ...config import Config
        from ...container import Container
        container = Container(Config.from_env())
    config = container.config

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if start_background:
            # Check the database before starting the pool, so problems fail clearly (after retries).
            await _check_database(container)
            container.open_pool()
            if config.scheduler_enabled:
                from ..scheduler import AppScheduler
                scheduler = container.scheduler = AppScheduler(container).start()
        yield
        if scheduler:
            scheduler.shutdown()
        container.close_pool()

    app = FastAPI(title="JobHunter API", version="0.2.0", lifespan=lifespan)
    app.state.container = container
    app.state.verifier = TokenVerifier(config.supabase_url, config.supabase_jwt_secret, config.allowed_user_email)
    app.add_middleware(CORSMiddleware, allow_origins=list(config.web_origins), allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(errors.JobHunterError)
    async def domain_error(_: Request, exc: errors.JobHunterError):
        status = next((code for cls, code in STATUS if isinstance(exc, cls)), 400)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)

    from psycopg import OperationalError
    from psycopg_pool import PoolTimeout

    async def db_unavailable(_: Request, exc: Exception):
        # Specific exception classes (not bare Exception) run inside CORS, so the browser sees the message.
        log.warning("database unavailable: %s", str(exc).splitlines()[0])
        return JSONResponse({"detail": "Database temporarily unreachable. Retry in a moment."}, status_code=503)

    app.add_exception_handler(OperationalError, db_unavailable)
    app.add_exception_handler(PoolTimeout, db_unavailable)

    for r in (health, profile, settings, jobs, runs, applications, contacts, gmail, tracker, insights, misc):
        app.include_router(r.router)
    return app
