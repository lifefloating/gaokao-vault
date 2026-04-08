from __future__ import annotations

import asyncpg


async def upsert_special_enrollment(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO special_enrollments (enrollment_type, school_id, year, title, content,
            publish_date, source_url, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        data["enrollment_type"],
        data.get("school_id"),
        data["year"],
        data.get("title"),
        data.get("content"),
        data.get("publish_date"),
        data.get("source_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"] if row else 0
