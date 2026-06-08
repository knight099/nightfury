import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.core.database import async_session_factory, engine
from app.core.middleware import RequestIDMiddleware, TimingMiddleware
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
from app.api.digests import router as digests_router
from app.api.chat import router as chat_router
from app.ws.events import router as ws_router
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
    # Schema is managed by Alembic. Run `alembic upgrade head` before booting
    # the API in any environment (dev, staging, prod).
    await seed_super_admin()
    scheduler = None
    if APSCHEDULER_AVAILABLE:
        try:
            scheduler = start_scheduler()
            if scheduler is not None:
                await schedule_all(scheduler)
                app.state.digest_scheduler = scheduler
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
    await engine.dispose()


app = FastAPI(
    title="Nightwatch API",
    description="AI CCTV Event Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(TimingMiddleware)

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
app.include_router(digests_router)
app.include_router(chat_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
