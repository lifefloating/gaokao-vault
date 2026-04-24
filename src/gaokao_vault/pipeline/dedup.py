from __future__ import annotations

import json
from typing import Any

import asyncpg

from gaokao_vault.db.queries.crawl_meta import find_latest_hash, insert_snapshot

TABLE_MAP: dict[str, tuple[str, str, list[str]]] = {
    "schools": ("schools", "sch_id = $1", ["sch_id"]),
    "school_satisfaction": ("school_satisfaction", "school_id = $1 AND year = $2", ["school_id", "year"]),
    "major_categories": ("major_categories", "name = $1 AND education_level = $2", ["name", "education_level"]),
    "major_subcategories": ("major_subcategories", "category_id = $1 AND name = $2", ["category_id", "name"]),
    "majors": ("majors", "code = $1 AND education_level = $2", ["code", "education_level"]),
    "school_majors": ("school_majors", "school_id = $1 AND major_id = $2", ["school_id", "major_id"]),
    "major_satisfaction": ("major_satisfaction", "major_id = $1 AND school_id = $2", ["major_id", "school_id"]),
    "score_lines": (
        "admission_score_lines",
        "province_id = $1 AND year = $2 AND subject_category_id = $3 AND batch = $4 AND special_name IS NOT DISTINCT FROM $5",
        ["province_id", "year", "subject_category_id", "batch", "special_name"],
    ),
    "charters": ("admission_charters", "school_id = $1 AND year = $2", ["school_id", "year"]),
    "timelines": (
        "volunteer_timelines",
        "province_id = $1 AND year = $2 AND batch = $3",
        ["province_id", "year", "batch"],
    ),
    "enrollment_plans": (
        "enrollment_plans",
        "school_id = $1 AND province_id = $2 AND year = $3 "
        "AND subject_category_id IS NOT DISTINCT FROM $4 "
        "AND batch IS NOT DISTINCT FROM $5 AND major_name IS NOT DISTINCT FROM $6",
        ["school_id", "province_id", "year", "subject_category_id", "batch", "major_name"],
    ),
    "major_admission_results": (
        "major_admission_results",
        "school_id = $1 AND major_id = $2 AND province_id = $3 AND year = $4 "
        "AND subject_category_id IS NOT DISTINCT FROM $5 AND batch = $6",
        ["school_id", "major_id", "province_id", "year", "subject_category_id", "batch"],
    ),
    "special_enrollments": (
        "special_enrollments",
        "enrollment_type = $1 AND school_id IS NOT DISTINCT FROM $2 AND year = $3 AND title IS NOT DISTINCT FROM $4",
        ["enrollment_type", "school_id", "year", "title"],
    ),
    "major_interpretations": (
        "major_interpretations",
        "major_id IS NOT DISTINCT FROM $1 AND title IS NOT DISTINCT FROM $2",
        ["major_id", "title"],
    ),
}


async def deduplicate_and_persist(
    db_pool: asyncpg.Pool,
    entity_type: str,
    item: dict[str, Any],
    content_hash: str,
    unique_keys: dict[str, Any],
    crawl_task_id: int,
    upsert_fn=None,
) -> str:
    mapping = TABLE_MAP.get(entity_type)
    if mapping is None and upsert_fn is None:
        return "failed"

    async with db_pool.acquire() as conn, conn.transaction():
        if mapping:
            table, clause, key_fields = mapping
            params = [unique_keys[k] for k in key_fields]
            existing_id, existing_hash = await find_latest_hash(conn, table, clause, params)
        else:
            existing_id, existing_hash = None, None

        item["content_hash"] = content_hash
        item["crawl_task_id"] = crawl_task_id

        if existing_id is None:
            entity_id = await _persist_new(conn, item, upsert_fn)
            if not entity_id:
                return "failed"
            await insert_snapshot(conn, crawl_task_id, entity_type, entity_id, content_hash, "new")
            return "new"

        if existing_hash == content_hash:
            await insert_snapshot(conn, crawl_task_id, entity_type, existing_id, content_hash, "unchanged")
            return "unchanged"

        old_data = await _fetch_existing_row(conn, mapping, existing_id)
        entity_id = await _persist_updated(conn, item, existing_id, upsert_fn)
        if not entity_id:
            return "failed"

        await insert_snapshot(
            conn,
            crawl_task_id,
            entity_type,
            entity_id,
            content_hash,
            "updated",
            previous_hash=existing_hash,
            snapshot_data=_serialize_snapshot(old_data),
        )
        return "updated"


async def _persist_new(conn: asyncpg.Connection, item: dict[str, Any], upsert_fn) -> int | None:
    if upsert_fn is None:
        return None
    return await upsert_fn(conn, item)


async def _persist_updated(
    conn: asyncpg.Connection,
    item: dict[str, Any],
    existing_id: int,
    upsert_fn,
) -> int | None:
    if upsert_fn is None:
        return existing_id
    return await upsert_fn(conn, item)


async def _fetch_existing_row(
    conn: asyncpg.Connection,
    mapping: tuple[str, str, list[str]] | None,
    existing_id: int,
) -> dict | None:
    if mapping is None:
        return None
    row = await conn.fetchrow(f"SELECT * FROM {mapping[0]} WHERE id = $1", existing_id)  # noqa: S608
    return dict(row) if row else None


def _serialize_snapshot(data: dict | None) -> dict | None:
    if data is None:
        return None
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))
