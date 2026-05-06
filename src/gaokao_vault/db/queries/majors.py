from __future__ import annotations

import json

import asyncpg

_MAJOR_STRENGTH_FIELDS = ("major_strength_rank", "major_strength_score", "major_strength_tier")


def _has_major_strength_data(data: dict) -> bool:
    return any(data.get(field) is not None for field in _MAJOR_STRENGTH_FIELDS) or bool(data.get("strength_evidence"))


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
        INSERT INTO majors (source_id, category_id, subcategory_id, code, name, education_level,
            duration, degree, description, employment_rate, graduate_directions,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (code, education_level) DO UPDATE SET
            source_id=EXCLUDED.source_id, category_id=EXCLUDED.category_id, subcategory_id=EXCLUDED.subcategory_id,
            name=EXCLUDED.name, duration=EXCLUDED.duration, degree=EXCLUDED.degree,
            description=EXCLUDED.description, employment_rate=EXCLUDED.employment_rate,
            graduate_directions=EXCLUDED.graduate_directions,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data.get("source_id"),
        data.get("category_id"),
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
    has_strength_data = _has_major_strength_data(data)
    strength_evidence = data.get("strength_evidence")
    row = await conn.fetchrow(
        """
        INSERT INTO school_majors (
            school_id, major_id, school_major_display_order, major_strength_rank,
            major_strength_score, major_strength_tier, is_featured_major,
            strength_evidence, content_hash, crawl_task_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, FALSE), COALESCE($8::jsonb, '[]'::jsonb), $9, $10)
        ON CONFLICT (school_id, major_id) DO UPDATE SET
            school_major_display_order=EXCLUDED.school_major_display_order,
            major_strength_rank=CASE WHEN $11 THEN EXCLUDED.major_strength_rank ELSE school_majors.major_strength_rank END,
            major_strength_score=CASE WHEN $11 THEN EXCLUDED.major_strength_score ELSE school_majors.major_strength_score END,
            major_strength_tier=CASE WHEN $11 THEN EXCLUDED.major_strength_tier ELSE school_majors.major_strength_tier END,
            is_featured_major=CASE WHEN $11 THEN EXCLUDED.is_featured_major ELSE school_majors.is_featured_major END,
            strength_evidence=CASE WHEN $11 THEN EXCLUDED.strength_evidence ELSE school_majors.strength_evidence END,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["major_id"],
        data.get("school_major_display_order"),
        data.get("major_strength_rank"),
        data.get("major_strength_score"),
        data.get("major_strength_tier"),
        data.get("is_featured_major") if has_strength_data else False,
        json.dumps(strength_evidence, ensure_ascii=False)
        if has_strength_data and strength_evidence is not None
        else None,
        data.get("content_hash"),
        data.get("crawl_task_id"),
        has_strength_data,
    )
    return row["id"]


async def upsert_school_major_strength_signal(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO school_major_strength_signals (
            school_id, major_id, signal_type, signal_level, strength_score,
            source_url, evidence_title, evidence_year, content_hash, crawl_task_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (school_id, major_id, signal_type, signal_level, evidence_year) DO UPDATE SET
            strength_score=EXCLUDED.strength_score,
            source_url=EXCLUDED.source_url,
            evidence_title=EXCLUDED.evidence_title,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id,
            updated_at=NOW()
        RETURNING id
        """,
        data["school_id"],
        data["major_id"],
        data["signal_type"],
        data.get("signal_level"),
        data["strength_score"],
        data.get("source_url"),
        data.get("evidence_title"),
        data.get("evidence_year"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def refresh_school_major_strength_rollup(conn: asyncpg.Connection) -> str:
    return await conn.execute(
        """
        WITH ranked AS (
            SELECT
                school_id,
                major_id,
                major_strength_score,
                strength_evidence,
                ROW_NUMBER() OVER (
                    PARTITION BY school_id
                    ORDER BY major_strength_score DESC, major_id
                ) AS major_strength_rank
            FROM (
                SELECT
                    school_id,
                    major_id,
                    SUM(strength_score) AS major_strength_score,
                    JSONB_AGG(
                        JSONB_BUILD_OBJECT(
                            'signal_type', signal_type,
                            'signal_level', signal_level,
                            'strength_score', strength_score,
                            'source_url', source_url,
                            'evidence_title', evidence_title,
                            'evidence_year', evidence_year
                        )
                        ORDER BY strength_score DESC, signal_type, evidence_year DESC NULLS LAST
                    ) AS strength_evidence
                FROM school_major_strength_signals
                GROUP BY school_id, major_id
            ) evidence
        )
        UPDATE school_majors sm
        SET
            major_strength_rank = ranked.major_strength_rank,
            major_strength_score = ranked.major_strength_score,
            major_strength_tier = CASE
                WHEN ranked.major_strength_score >= 100 THEN 'national'
                WHEN ranked.major_strength_score >= 70 THEN 'provincial'
                WHEN ranked.major_strength_score IS NOT NULL THEN 'evidence'
                ELSE NULL
            END,
            is_featured_major = COALESCE(ranked.major_strength_rank <= 3, FALSE),
            strength_evidence = COALESCE(ranked.strength_evidence, '[]'::jsonb)
        FROM school_majors target
        LEFT JOIN ranked
            ON ranked.school_id = target.school_id
           AND ranked.major_id = target.major_id
        WHERE sm.id = target.id
        """
    )


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


async def find_school_major_id_by_name(
    conn: asyncpg.Connection,
    school_id: int,
    major_name: str,
    *,
    education_level: str | None = None,
    fallback_to_unique_major: bool = False,
) -> int | None:
    rows = await conn.fetch(
        """
        SELECT m.id
        FROM school_majors sm
        JOIN majors m ON m.id = sm.major_id
        WHERE sm.school_id = $1
          AND m.name = $2
          AND ($3::text IS NULL OR m.education_level = $3)
        ORDER BY m.id
        """,
        school_id,
        major_name,
        education_level,
    )
    if len(rows) == 1:
        return rows[0]["id"]
    if len(rows) > 1 or not fallback_to_unique_major:
        return None

    rows = await conn.fetch(
        """
        SELECT id
        FROM majors
        WHERE name = $1
          AND ($2::text IS NULL OR education_level = $2)
        ORDER BY id
        """,
        major_name,
        education_level,
    )
    return rows[0]["id"] if len(rows) == 1 else None


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
