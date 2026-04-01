from __future__ import annotations

import logging
from typing import Any

import asyncpg

from gaokao_vault.db.queries.crawl_meta import create_task, update_task_stats

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages crawl_task lifecycle: create, track, finalize."""

    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool

    async def start_task(self, task_type: str, params: dict[str, Any] | None = None) -> int:
        task_id = await create_task(self.db_pool, task_type, params)
        logger.info("Started crawl task %d for %s", task_id, task_type)
        return task_id

    async def finish_task(
        self,
        task_id: int,
        stats: dict[str, int],
        error: str | None = None,
    ) -> None:
        await update_task_stats(self.db_pool, task_id, stats, error)
        status = "failed" if error else "success"
        logger.info("Finished crawl task %d with status=%s stats=%s", task_id, status, stats)

    async def get_task_status(self, task_id: int) -> dict | None:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM crawl_tasks WHERE id = $1", task_id)
            return dict(row) if row else None

    async def list_recent_tasks(self, limit: int = 20) -> list[dict]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, task_type, status, started_at, finished_at, "
                "total_items, new_items, updated_items, unchanged_items, failed_items "
                "FROM crawl_tasks ORDER BY id DESC LIMIT $1",
                limit,
            )
            return [dict(r) for r in rows]
