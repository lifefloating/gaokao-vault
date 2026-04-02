from __future__ import annotations

import asyncpg


async def upsert_score_line(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO admission_score_lines (province_id, year, subject_category_id, batch, score, note,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (province_id, year, subject_category_id, batch) DO UPDATE SET
            score=EXCLUDED.score, note=EXCLUDED.note,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["province_id"],
        data["year"],
        data.get("subject_category_id"),
        data["batch"],
        data.get("score"),
        data.get("note"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def batch_upsert_score_segments(conn: asyncpg.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    count = 0
    for data in rows:
        await conn.execute(
            """
            INSERT INTO score_segments (province_id, year, subject_category_id, score,
                segment_count, cumulative_count, content_hash, crawl_task_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (province_id, year, subject_category_id, score) DO UPDATE SET
                segment_count=EXCLUDED.segment_count, cumulative_count=EXCLUDED.cumulative_count,
                content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
            """,
            data["province_id"],
            data["year"],
            data.get("subject_category_id"),
            data["score"],
            data["segment_count"],
            data["cumulative_count"],
            data.get("content_hash"),
            data.get("crawl_task_id"),
        )
        count += 1
    return count
