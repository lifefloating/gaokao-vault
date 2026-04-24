from __future__ import annotations

import asyncpg


async def upsert_major_category(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_categories (name, education_level, code)
        VALUES ($1, $2, $3)
        ON CONFLICT (name, education_level) DO UPDATE SET code=EXCLUDED.code
        RETURNING id
        """,
        data["name"],
        data["education_level"],
        data.get("code"),
    )
    return row["id"]


async def upsert_major_subcategory(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_subcategories (category_id, name, code)
        VALUES ($1, $2, $3)
        ON CONFLICT (category_id, name) DO UPDATE SET code=EXCLUDED.code
        RETURNING id
        """,
        data["category_id"],
        data["name"],
        data.get("code"),
    )
    return row["id"]


async def upsert_major(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO majors (source_id, subcategory_id, code, name, education_level,
            duration, degree, description, employment_rate, graduate_directions,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (code, education_level) DO UPDATE SET
            source_id=EXCLUDED.source_id, subcategory_id=EXCLUDED.subcategory_id,
            name=EXCLUDED.name, duration=EXCLUDED.duration, degree=EXCLUDED.degree,
            description=EXCLUDED.description, employment_rate=EXCLUDED.employment_rate,
            graduate_directions=EXCLUDED.graduate_directions,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data.get("source_id"),
        data.get("subcategory_id"),
        data.get("code"),
        data["name"],
        data["education_level"],
        data.get("duration"),
        data.get("degree"),
        data.get("description"),
        data.get("employment_rate"),
        data.get("graduate_directions"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_school_major(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO school_majors (school_id, major_id, content_hash, crawl_task_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (school_id, major_id) DO UPDATE SET
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["major_id"],
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def find_major_by_code(conn: asyncpg.Connection, code: str) -> dict | None:
    rows = await conn.fetch("SELECT id, code, name FROM majors WHERE code = $1 ORDER BY id", code)
    if len(rows) != 1:
        return None
    return dict(rows[0])


async def find_major_by_source_id(conn: asyncpg.Connection, source_id: str) -> dict | None:
    rows = await conn.fetch("SELECT id, source_id, code, name FROM majors WHERE source_id = $1 ORDER BY id", source_id)
    if len(rows) != 1:
        return None
    return dict(rows[0])


async def find_majors_by_name(conn: asyncpg.Connection, name: str) -> list[dict]:
    rows = await conn.fetch("SELECT id, code, name FROM majors WHERE name = $1 ORDER BY id", name)
    return [dict(row) for row in rows]


async def upsert_major_satisfaction(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_satisfaction (major_id, school_id, overall_score, vote_count,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (major_id, school_id) DO UPDATE SET
            overall_score=EXCLUDED.overall_score, vote_count=EXCLUDED.vote_count,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["major_id"],
        data.get("school_id"),
        data.get("overall_score"),
        data.get("vote_count"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_major_interpretation(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_interpretations (major_id, title, content, author, publish_date,
            source_url, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (major_id, title) DO UPDATE SET
            content=EXCLUDED.content,
            author=EXCLUDED.author,
            publish_date=EXCLUDED.publish_date,
            source_url=EXCLUDED.source_url,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data.get("major_id"),
        data.get("title"),
        data["content"],
        data.get("author"),
        data.get("publish_date"),
        data.get("source_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
