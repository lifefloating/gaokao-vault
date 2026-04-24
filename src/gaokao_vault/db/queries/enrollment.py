from __future__ import annotations

import asyncpg


async def upsert_enrollment_plan(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO enrollment_plans (school_id, province_id, year, subject_category_id,
            batch, major_name, major_id, plan_count, duration, tuition, note,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (school_id, province_id, year, subject_category_id, batch, major_name) DO UPDATE SET
            major_id=EXCLUDED.major_id,
            plan_count=EXCLUDED.plan_count,
            duration=EXCLUDED.duration,
            tuition=EXCLUDED.tuition,
            note=EXCLUDED.note,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["province_id"],
        data["year"],
        data.get("subject_category_id"),
        data.get("batch"),
        data.get("major_name"),
        data.get("major_id"),
        data.get("plan_count"),
        data.get("duration"),
        data.get("tuition"),
        data.get("note"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_charter(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO admission_charters (school_id, year, title, content, publish_date,
            source_url, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (school_id, year) DO UPDATE SET
            title=EXCLUDED.title, content=EXCLUDED.content,
            publish_date=EXCLUDED.publish_date, source_url=EXCLUDED.source_url,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["year"],
        data.get("title"),
        data["content"],
        data.get("publish_date"),
        data.get("source_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_timeline(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO volunteer_timelines (province_id, year, batch, start_time, end_time, note,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (province_id, year, batch) DO UPDATE SET
            start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time, note=EXCLUDED.note,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["province_id"],
        data["year"],
        data["batch"],
        data.get("start_time"),
        data.get("end_time"),
        data.get("note"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
