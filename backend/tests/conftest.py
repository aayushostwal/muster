"""Shared pytest fixtures: an in-memory sqlite AsyncSession used to override get_db."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base


@pytest_asyncio.fixture
async def db_engine():
    """A single shared in-memory sqlite connection, alive for the test's duration."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def override_get_db(db_engine):
    """A get_db-compatible dependency bound to the test's in-memory engine."""
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    return _get_db
