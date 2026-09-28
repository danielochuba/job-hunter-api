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
          (errors.Forbidden, 403)]


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
            container.open_pool()
            with container.session() as ctx:
                ctx.repos.runs.mark_interrupted()
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

    for r in (health, profile, settings, jobs, runs, applications, contacts, gmail, tracker, insights, misc):
        app.include_router(r.router)
    return app
