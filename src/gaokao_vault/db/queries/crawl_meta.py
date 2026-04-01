from __future__ import annotations

import json
from typing import Any

import asyncpg


async def create_task(pool: asyncpg.Pool, task_type: str, params: dict | None = None) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO crawl_tasks (task_type, status, started_at, params)
            VALUES ($1, 'running', NOW(), $2)
            RETURNING id
            """,
            task_type,
            json.dumps(params) if params else None,
        )
        return row["id"]


async def update_task_stats(pool: asyncpg.Pool, task_id: int, stats: dict[str, int], error: str | None = None) -> None:
    status = "failed" if error else "success"
    total = stats.get("new", 0) + stats.get("updated", 0) + stats.get("unchanged", 0) + stats.get("failed", 0)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE crawl_tasks
            SET status = $2, finished_at = NOW(),
                total_items = $3, new_items = $4, updated_items = $5,
                unchanged_items = $6, failed_items = $7, error_message = $8
            WHERE id = $1
            """,
            task_id,
            status,
            total,
            stats.get("new", 0),
            stats.get("updated", 0),
            stats.get("unchanged", 0),
            stats.get("failed", 0),
            error,
        )


async def insert_snapshot(
    conn: asyncpg.Connection,
    crawl_task_id: int,
    entity_type: str,
    entity_id: int,
    content_hash: str,
    change_type: str,
    previous_hash: str | None = None,
    snapshot_data: dict[str, Any] | None = None,
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO crawl_snapshots (crawl_task_id, entity_type, entity_id, content_hash, change_type, previous_hash, snapshot_data)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        crawl_task_id,
        entity_type,
        entity_id,
        content_hash,
        change_type,
        previous_hash,
        json.dumps(snapshot_data, ensure_ascii=False, default=str) if snapshot_data else None,
    )
    return row["id"]


async def find_latest_hash(
    conn: asyncpg.Connection, table: str, unique_clause: str, params: list
) -> tuple[int | None, str | None]:
    row = await conn.fetchrow(
        f"SELECT id, content_hash FROM {table} WHERE {unique_clause}",  # noqa: S608
        *params,
    )
    if row is None:
        return None, None
    return row["id"], row["content_hash"]
