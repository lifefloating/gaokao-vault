from __future__ import annotations

import asyncpg

from gaokao_vault.config import DatabaseConfig

_pool: asyncpg.Pool | None = None


async def create_pool(config: DatabaseConfig | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    if config is None:
        config = DatabaseConfig()
    _pool = await asyncpg.create_pool(
        dsn=config.dsn,
        min_size=config.pool_min,
        max_size=config.pool_max,
    )
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        msg = "Database pool not initialized. Call create_pool() first."
        raise RuntimeError(msg)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
