from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

_SQL_DIR = Path(__file__).parent


async def run_migrations(pool: asyncpg.Pool) -> None:
    schema_sql = (_SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    seed_provinces = (_SQL_DIR / "seed_provinces.sql").read_text(encoding="utf-8")
    seed_categories = (_SQL_DIR / "seed_subject_categories.sql").read_text(encoding="utf-8")

    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
        logger.info("Schema applied successfully")

        await conn.execute(seed_provinces)
        logger.info("Provinces seeded")

        await conn.execute(seed_categories)
        logger.info("Subject categories seeded")
