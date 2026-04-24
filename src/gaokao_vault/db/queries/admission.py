from __future__ import annotations

import asyncpg


async def upsert_major_admission_result(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_admission_results (
            school_id, major_id, province_id, year, subject_category_id, batch,
            min_score, min_rank, avg_score, avg_rank, max_score, max_rank,
            admitted_count, major_name_raw, subject_category_raw, batch_raw, remark,
            source_url, content_hash, crawl_task_id
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
        ON CONFLICT (school_id, major_id, province_id, year, subject_category_id, batch) DO UPDATE SET
            min_score=EXCLUDED.min_score,
            min_rank=EXCLUDED.min_rank,
            avg_score=EXCLUDED.avg_score,
            avg_rank=EXCLUDED.avg_rank,
            max_score=EXCLUDED.max_score,
            max_rank=EXCLUDED.max_rank,
            admitted_count=EXCLUDED.admitted_count,
            major_name_raw=EXCLUDED.major_name_raw,
            subject_category_raw=EXCLUDED.subject_category_raw,
            batch_raw=EXCLUDED.batch_raw,
            remark=EXCLUDED.remark,
            source_url=EXCLUDED.source_url,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["major_id"],
        data["province_id"],
        data["year"],
        data.get("subject_category_id"),
        data["batch"],
        data.get("min_score"),
        data.get("min_rank"),
        data.get("avg_score"),
        data.get("avg_rank"),
        data.get("max_score"),
        data.get("max_rank"),
        data.get("admitted_count"),
        data.get("major_name_raw"),
        data.get("subject_category_raw"),
        data.get("batch_raw"),
        data.get("remark"),
        data.get("source_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
