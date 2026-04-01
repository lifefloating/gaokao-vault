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
        "province_id = $1 AND year = $2 AND subject_category_id = $3 AND batch = $4",
        ["province_id", "year", "subject_category_id", "batch"],
    ),
    "charters": ("admission_charters", "school_id = $1 AND year = $2", ["school_id", "year"]),
    "timelines": (
        "volunteer_timelines",
        "province_id = $1 AND year = $2 AND batch = $3",
        ["province_id", "year", "batch"],
    ),
    "enrollment_plans": (
        "enrollment_plans",
        "school_id = $1 AND province_id = $2 AND year = $3 AND major_name = $4",
        ["school_id", "province_id", "year", "major_name"],
    ),
    "special_enrollments": (
        "special_enrollments",
        "enrollment_type = $1 AND school_id = $2 AND year = $3",
        ["enrollment_type", "school_id", "year"],
    ),
    "announcements": (
        "provincial_announcements",
        "province_id = $1 AND title = $2",
        ["province_id", "title"],
    ),
    "major_interpretations": (
        "major_interpretations",
        "major_id = $1 AND title = $2",
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

    async with db_pool.acquire() as conn:
        if mapping:
            table, clause, key_fields = mapping
            params = [unique_keys[k] for k in key_fields]
            existing_id, existing_hash = await find_latest_hash(conn, table, clause, params)
        else:
            existing_id, existing_hash = None, None

        item["content_hash"] = content_hash
        item["crawl_task_id"] = crawl_task_id

        if existing_id is None:
            if upsert_fn:
                entity_id = await upsert_fn(conn, item)
            elif mapping:
                # No upsert_fn and no existing record — cannot insert without upsert_fn
                return "failed"
            else:
                return "failed"
            await insert_snapshot(conn, crawl_task_id, entity_type, entity_id, content_hash, "new")
            return "new"

        if existing_hash == content_hash:
            await insert_snapshot(conn, crawl_task_id, entity_type, existing_id, content_hash, "unchanged")
            return "unchanged"

        old_data = None
        if mapping:
            row = await conn.fetchrow(f"SELECT * FROM {mapping[0]} WHERE id = $1", existing_id)  # noqa: S608
            if row:
                old_data = dict(row)

        if upsert_fn:
            entity_id = await upsert_fn(conn, item)
        else:
            entity_id = existing_id

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


def _serialize_snapshot(data: dict | None) -> dict | None:
    if data is None:
        return None
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))
