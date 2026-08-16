"""Engine/session. SQLite сейчас, Postgres — сменой DATABASE_URL, без изменения кода."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


_engine_kwargs = {}
if settings.is_sqlite():
    # NullPool-подобное поведение SQLite не требует пула вовсе; WAL для конкурентного чтения.
    _engine_kwargs['connect_args'] = {'timeout': 30}
else:
    _engine_kwargs['pool_size'] = 5
    _engine_kwargs['pool_recycle'] = 1800
    _engine_kwargs['pool_pre_ping'] = True

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_sqlite_pragmas() -> None:
    """WAL-режим для SQLite — совпадающий с Bedolaga подход для локальной разработки."""
    if not settings.is_sqlite():
        return
    async with engine.begin() as conn:
        await conn.exec_driver_sql('PRAGMA journal_mode=WAL')
        await conn.exec_driver_sql('PRAGMA busy_timeout=30000')
