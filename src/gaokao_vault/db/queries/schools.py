from __future__ import annotations

import asyncpg


async def upsert_school(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO schools (sch_id, name, province_id, city, authority, level,
            is_211, is_985, is_double_first, is_private, is_independent, is_sino_foreign,
            school_type, website, phone, email, address, introduction, logo_url,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
        ON CONFLICT (sch_id) DO UPDATE SET
            name=EXCLUDED.name, province_id=COALESCE(EXCLUDED.province_id, schools.province_id), city=EXCLUDED.city,
            authority=EXCLUDED.authority, level=EXCLUDED.level,
            is_211=EXCLUDED.is_211, is_985=EXCLUDED.is_985, is_double_first=EXCLUDED.is_double_first,
            is_private=EXCLUDED.is_private, is_independent=EXCLUDED.is_independent,
            is_sino_foreign=EXCLUDED.is_sino_foreign, school_type=EXCLUDED.school_type,
            website=EXCLUDED.website, phone=EXCLUDED.phone, email=EXCLUDED.email,
            address=EXCLUDED.address, introduction=EXCLUDED.introduction, logo_url=EXCLUDED.logo_url,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["sch_id"],
        data["name"],
        data.get("province_id"),
        data.get("city"),
        data.get("authority"),
        data.get("level"),
        data.get("is_211", False),
        data.get("is_985", False),
        data.get("is_double_first", False),
        data.get("is_private", False),
        data.get("is_independent", False),
        data.get("is_sino_foreign", False),
        data.get("school_type"),
        data.get("website"),
        data.get("phone"),
        data.get("email"),
        data.get("address"),
        data.get("introduction"),
        data.get("logo_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def find_school_by_sch_id(conn: asyncpg.Connection, sch_id: int) -> dict | None:
    row = await conn.fetchrow("SELECT id, sch_id, name, province_id FROM schools WHERE sch_id = $1", sch_id)
    return dict(row) if row else None


async def upsert_school_satisfaction(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO school_satisfaction (school_id, year, overall_score, environment_score, life_score,
            vote_count, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (school_id, year) DO UPDATE SET
            overall_score=EXCLUDED.overall_score, environment_score=EXCLUDED.environment_score,
            life_score=EXCLUDED.life_score, vote_count=EXCLUDED.vote_count,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data.get("year"),
        data.get("overall_score"),
        data.get("environment_score"),
        data.get("life_score"),
        data.get("vote_count"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
