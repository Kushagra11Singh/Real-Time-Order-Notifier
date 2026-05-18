import logging
from pathlib import Path

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def create_db_pool() -> None:
    global _pool
    logger.info("Creating asyncpg connection pool…")
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await _apply_schema()
    logger.info("DB pool ready.")


async def _apply_schema() -> None:
    """Run schema.sql idempotently on startup so the table and trigger
    always exist without requiring a separate migration step."""
    ddl = SCHEMA_PATH.read_text()
    async with _pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("Schema applied.")


async def close_db_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        logger.info("DB pool closed.")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call create_db_pool() first.")
    return _pool
