"""Async engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    # Server-side statement caching interacts badly with pgbouncer in
    # transaction mode, which is how we will run in Azure. Disabling it costs
    # very little and removes a class of production-only failures.
    connect_args={"statement_cache_size": 0},
)

SessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session bound to one request.

    The session starts with no tenant bound. Row level security therefore
    denies access to every tenant-scoped table until a principal is resolved
    and `bind_tenant` is called. That ordering is deliberate: a route that
    forgets to authenticate reads nothing rather than reading everything.
    """
    async with SessionFactory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            await session.rollback()
            raise
