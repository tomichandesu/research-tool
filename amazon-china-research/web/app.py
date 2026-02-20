"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import init_db

logger = logging.getLogger(__name__)

_web_dir = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # --- Startup ---
    logger.info("Initializing database...")
    await init_db()

    # Seed admin user
    await _seed_admin()

    # Recover stale jobs left in "running" state from a previous crash
    await _recover_stale_jobs()

    # Start job queue worker
    from .services.job_queue import job_queue
    job_queue.start_worker()
    logger.info("Job queue worker started.")

    # Re-enqueue any pending jobs left from before restart
    await _requeue_pending_jobs(job_queue)

    # Start 1688 session keeper (auto-refresh every 12 hours)
    from .services.session_keeper import session_keeper_loop
    keeper_task = asyncio.create_task(session_keeper_loop())
    logger.info("1688 session keeper started.")

    yield

    # --- Shutdown ---
    # Clean up any active 1688 login sessions
    from .services.alibaba_login import login_session_manager
    await login_session_manager.cleanup_all()
    logger.info("1688 login sessions cleaned up.")

    keeper_task.cancel()
    try:
        await keeper_task
    except asyncio.CancelledError:
        pass
    logger.info("1688 session keeper stopped.")

    await job_queue.shutdown()
    logger.info("Job queue worker stopped.")


async def _recover_stale_jobs():
    """Reset jobs stuck in 'running' state back to 'pending' for automatic retry.

    On server restart, all worker processes are gone, so any job still marked
    as 'running' will never complete. Reset them to 'pending' so they get
    automatically re-queued and restarted without user intervention.
    """
    from sqlalchemy import select
    from .database import async_session_factory
    from .models import ResearchJob

    async with async_session_factory() as session:
        result = await session.execute(
            select(ResearchJob).where(ResearchJob.status == "running")
        )
        stale_jobs = list(result.scalars().all())

        if not stale_jobs:
            return

        for job in stale_jobs:
            job.status = "pending"
            job.progress_pct = 0
            job.progress_message = "サーバー再起動後に自動再開します..."
            job.started_at = None
            logger.info(f"Reset stale job {job.id} (keyword: {job.keyword}) to pending for retry")

        await session.commit()
        logger.info(f"Reset {len(stale_jobs)} stale job(s) to pending")


async def _requeue_pending_jobs(job_queue):
    """Re-enqueue any pending jobs that were lost when the server restarted."""
    from sqlalchemy import select
    from .database import async_session_factory
    from .models import ResearchJob

    async with async_session_factory() as session:
        result = await session.execute(
            select(ResearchJob)
            .where(ResearchJob.status == "pending")
            .order_by(ResearchJob.created_at.asc())
        )
        pending_jobs = list(result.scalars().all())

        for job in pending_jobs:
            await job_queue.enqueue(job.id, job.user_id)
            logger.info(f"Re-enqueued pending job {job.id} (keyword: {job.keyword})")

        if pending_jobs:
            logger.info(f"Re-enqueued {len(pending_jobs)} pending job(s)")


async def _seed_admin():
    """Create the initial admin user if no users exist."""
    from sqlalchemy import select, func as sa_func
    from .database import async_session_factory
    from .models import User
    from .auth.service import hash_password

    async with async_session_factory() as session:
        count = await session.scalar(select(sa_func.count()).select_from(User))
        if count and count > 0:
            return

        admin = User(
            email=settings.ADMIN_EMAIL,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            display_name=settings.ADMIN_DISPLAY_NAME,
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        logger.info(f"Admin user created: {settings.ADMIN_EMAIL}")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Amazon-1688 Research Tool",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Session middleware (cookie-based session id transport)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        session_cookie="session_id",
        max_age=settings.SESSION_MAX_AGE_HOURS * 3600,
        https_only=False,  # Set True in production behind HTTPS
    )

    # Static files
    app.mount(
        "/static",
        StaticFiles(directory=str(_web_dir / "static")),
        name="static",
    )

    # Jinja2 templates (shared instance on app.state)
    import json as _json
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    _JST = _tz(_td(hours=9))
    templates = Jinja2Templates(directory=str(_web_dir / "templates"))
    templates.env.globals["now"] = _dt.utcnow
    templates.env.filters["from_json"] = lambda s: _json.loads(s) if s else None
    templates.env.filters["jst"] = lambda dt: dt.replace(tzinfo=_tz.utc).astimezone(_JST).strftime('%Y-%m-%d %H:%M') if dt else ""
    app.state.templates = templates

    # Register routes
    from .routes import auth as auth_routes
    from .routes import dashboard as dashboard_routes
    from .routes import research as research_routes
    from .routes import admin as admin_routes
    from .routes import billing as billing_routes
    from .routes import account as account_routes

    app.include_router(auth_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(research_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(billing_routes.router)
    app.include_router(account_routes.router)

    return app
