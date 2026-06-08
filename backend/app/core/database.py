from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        connect_args = {}
        url = settings.database_url
        # pooler.supabase.com = Supavisor (connection pooler) — SSL not needed
        # db.supabase.co = direct connection — SSL required
        if "db.supabase.co" in url:
            connect_args = {"ssl": "require"}
        elif "pooler.supabase.com" in url:
            connect_args = {"ssl": False}
        _engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=settings.debug,
            connect_args=connect_args,
        )
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine, _session_factory


# Keep module-level names for backward compatibility (lifespan uses engine.dispose())
class _LazyEngine:
    def __getattr__(self, name):
        return getattr(_get_engine()[0], name)

class _LazySessionFactory:
    def __call__(self, *a, **kw):
        return _get_engine()[1](*a, **kw)

engine = _LazyEngine()
async_session_factory = _LazySessionFactory()


async def get_db():
    _, factory = _get_engine()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
