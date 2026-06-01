import asyncio
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import hash_password
from app.main import app
from app.models.base import Base
from app.models.organization import Organization
from app.models.user import User

TEST_DB_URL = settings.database_url


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Rate-limit windows accumulate in shared Redis across test runs and
    produce flaky 429s. Disable globally for tests; dedicated rate-limit
    tests opt back in explicitly."""
    from app.config import settings as _s
    prev = _s.rate_limit_enabled
    _s.rate_limit_enabled = False
    yield
    _s.rate_limit_enabled = prev


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis_pool():
    """Recreate the module-level redis pool per-test.

    The application caches a `redis.ConnectionPool` at import time. Because each
    pytest-asyncio test runs on a fresh event loop, connections opened against
    the pool in one test become unusable in the next. Recreating the pool per
    test keeps every test isolated.
    """
    import redis.asyncio as redis_async

    from app.core import redis as redis_module

    redis_module.redis_pool = redis_async.ConnectionPool.from_url(
        settings.redis_url, decode_responses=True
    )
    yield
    try:
        await redis_module.redis_pool.disconnect(inuse_connections=True)
    except Exception:
        pass


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession) -> Organization:
    org = Organization(name="Test Org", slug=f"test-org-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_org: Organization) -> User:
    user = User(
        org_id=test_org.id,
        username=f"user-{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("testpass"),
        name="Test User",
        role="owner",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def super_admin(db_session: AsyncSession) -> User:
    admin = User(
        org_id=None,
        username=f"admin-{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("testpass"),
        name="Test Admin",
        role="super_admin",
    )
    db_session.add(admin)
    await db_session.flush()
    return admin


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(
    db_session: AsyncSession, test_user: User
) -> AsyncGenerator[AsyncClient, None]:
    """Client authenticated as a regular org owner via dependency override."""

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession, super_admin: User
) -> AsyncGenerator[AsyncClient, None]:
    """Client authenticated as super_admin via dependency override."""

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return super_admin

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
