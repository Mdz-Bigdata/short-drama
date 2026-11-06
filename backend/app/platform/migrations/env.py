from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app import settings
from app.platform.models import Base


def _run(connection) -> None:
    # render_as_batch: SQLite can only change a constraint by rebuilding the table.
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_from_command_line() -> None:
    engine = create_async_engine(settings.database_url())
    async with engine.begin() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("离线迁移不受支持：迁移需要读取当前的约束")

given = context.config.attributes.get("connection")
if given is not None:
    _run(given)
else:
    asyncio.run(_run_from_command_line())
