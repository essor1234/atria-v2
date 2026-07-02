"""SQLAlchemy AsyncEngine + sessionmaker, initialised from DATABASE_URL."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None
_engine_loop: Optional[asyncio.AbstractEventLoop] = None


def _normalize_url(url: str) -> str:
    """Force the asyncpg driver for SQLAlchemy."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def _build() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it to a PostgreSQL DSN, e.g. "
            "postgresql://user:password@localhost:5432/atria"
        )
    engine = create_async_engine(
        _normalize_url(url),
        pool_size=10,
        max_overflow=0,
        pool_pre_ping=True,
    )
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, sm


async def get_engine() -> AsyncEngine:
    """Return the shared AsyncEngine, rebuilding if its loop has been closed."""
    global _engine, _sessionmaker, _engine_loop
    if _engine is not None and _engine_loop is not None and _engine_loop.is_closed():
        _engine = None
        _sessionmaker = None
    if _engine is None:
        _engine, _sessionmaker = _build()
        _engine_loop = asyncio.get_running_loop()
    return _engine


async def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the shared async sessionmaker (creating engine on first call)."""
    await get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def close_engine() -> None:
    """Dispose of the AsyncEngine on shutdown."""
    global _engine, _sessionmaker, _engine_loop
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
    _engine_loop = None


async def init_schema() -> None:
    """Create all tables defined on Base.metadata if they do not exist; drop legacy module tables."""
    from atria.db.models import Base

    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Widen messages.role so block roles (e.g. custom_block) are not
        # truncated. Idempotent: ALTER to a wider VARCHAR is a no-op if already wide.
        try:
            await conn.execute(text("ALTER TABLE messages ALTER COLUMN role TYPE VARCHAR(32)"))
        except Exception as _alter_err:  # noqa: BLE001
            logger.warning("Failed to widen messages.role: %s", _alter_err)
        # Legacy DB-backed modules system removed; drop its tables if present.
        for _legacy in ("module_tasks", "module_tools", "modules"):
            try:
                await conn.execute(text(f"DROP TABLE IF EXISTS {_legacy} CASCADE"))
            except Exception as _drop_err:
                logger.warning("Failed to drop legacy table %s: %s", _legacy, _drop_err)
