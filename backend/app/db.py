from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import settings


class Base(DeclarativeBase):
    pass


# SQLite (unit tests) without pooling: connections must not cross the test client's event loops.
engine = (create_async_engine(settings.DATABASE_URL, poolclass=NullPool) if settings.DATABASE_URL.startswith("sqlite")
          else create_async_engine(settings.DATABASE_URL, pool_pre_ping=True))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s
