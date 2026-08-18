import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.core.database import async_session_factory, engine
from app.core.middleware import ImpersonationAuditMiddleware, RequestIDMiddleware, TimingMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.security import hash_password
from app.models.user import User

from app.api.auth import router as auth_router
from app.api.cameras import router as cameras_router
from app.api.events import router as events_router
from app.api.alerts import router as alerts_router
from app.api.sites import router as sites_router
from app.api.internal import router as internal_router
from app.api.admin import router as admin_router
from app.api.settings import router as settings_router
from app.api.test_camera import router as test_camera_router
from app.api.agents import router as agents_router
from app.api.camera_connections import router as camera_connections_router
from app.api.fleet import router as fleet_router
from app.api.digests import router as digests_router
from app.api.chat import router as chat_router
from app.api.devices import router as devices_router
from app.api.edge_uploads import router as edge_uploads_router
from app.api.edge_credentials import router as edge_credentials_router
from app.api.webrtc import router as webrtc_router
from app.api.agent_control import router as agent_control_router
from app.ws.events import router as ws_router
from app.services.alert_escalation import run_escalation_sweep
from app.services.fleet_health import run_fleet_health_sweep
from app.services.retention import run_retention_sweep
from app.services.digest.scheduler import (
    APSCHEDULER_AVAILABLE,
    schedule_all,
    start_scheduler,
)

logging.basicConfig(level=logging.INFO if not settings.debug else logging.DEBUG)
logger = logging.getLogger(__name__)


async def seed_super_admin():
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == settings.super_admin_username)
        )
        if result.scalar_one_or_none():
            logger.info(f"Super admin already exists: {settings.super_admin_username}")
            return

        admin = User(
            org_id=None,
            username=settings.super_admin_username,
            password_hash=hash_password(settings.super_admin_password),
            name="Super Admin",
            role="super_admin",
        )
        session.add(admin)
        await session.commit()
        logger.info(f"Super admin created: {settings.super_admin_username}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await seed_super_admin()
    except Exception:
        logger.exception("seed_super_admin failed — continuing startup")

    scheduler = None
    if APSCHEDULER_AVAILABLE:
        try:
            scheduler = start_scheduler()
            if scheduler is not None:
                await schedule_all(scheduler)
                app.state.digest_scheduler = scheduler
                # Escalation sweep. One minute is the resolution of the whole
                # ladder — rung delays are in seconds but nothing escalates
                # faster than the sweep runs, so sub-minute rungs would be a
                # promise the scheduler cannot keep.
                scheduler.add_job(
                    run_escalation_sweep,
                    "interval",
                    minutes=1,
                    id="alert_escalation_sweep",
                    max_instances=1,       # never overlap with a slow previous run
                    coalesce=True,         # a missed window runs once, not N times
                )
                # Fleet health / failover. Every minute so a dead appliance
                # is noticed promptly; the 5-minute staleness threshold inside
                # the sweep — not this interval — is what prevents flapping.
                scheduler.add_job(
                    run_fleet_health_sweep,
                    "interval",
                    minutes=1,
                    id="fleet_health_sweep",
                    max_instances=1,
                    coalesce=True,
                )
                # Retention purge. Daily and off-peak: it deletes media and
                # rows, so it should not compete with the evening digest run
                # or with normal daytime traffic.
                scheduler.add_job(
                    run_retention_sweep,
                    "cron",
                    hour=3,
                    minute=30,
                    id="event_retention_sweep",
                    max_instances=1,
                    coalesce=True,
                )
        except Exception:
            logger.exception("Failed to initialise digest scheduler")
    else:
        logger.warning("APScheduler not installed; scheduled digests disabled")
    logger.info("Nightwatch API started")
    yield
    # Shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("Error shutting down digest scheduler")
    try:
        await engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title="Nightwatch API",
    description="AI CCTV Event Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware — order matters: last added = outermost (first to handle request/response).
# CORSMiddleware must be outermost so CORS headers are present on ALL responses,
# including errors thrown by inner middleware (rate limiter, etc.).
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ImpersonationAuditMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router)
app.include_router(cameras_router)
app.include_router(events_router)
app.include_router(alerts_router)
app.include_router(sites_router)
app.include_router(internal_router)
app.include_router(admin_router)
app.include_router(settings_router)
app.include_router(test_camera_router)
app.include_router(agents_router)
app.include_router(fleet_router)
app.include_router(camera_connections_router)
app.include_router(digests_router)
app.include_router(chat_router)
app.include_router(devices_router)
app.include_router(edge_uploads_router)
app.include_router(edge_credentials_router)
app.include_router(webrtc_router)
app.include_router(agent_control_router)
app.include_router(ws_router)


@app.get("/health")
@app.get("/healthz")
async def health():
    return {"status": "ok", "service": settings.app_name}
