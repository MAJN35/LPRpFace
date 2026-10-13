"""Alembic environment (async engine from DATABASE_URL)."""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (register tables)

target_metadata = Base.metadata


def do_run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        await conn.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
