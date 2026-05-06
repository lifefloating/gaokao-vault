from __future__ import annotations

import json

import asyncpg

from gaokao_vault.pipeline.security import assert_allowed_source_url, sanitize_metadata


async def upsert_data_source(conn: asyncpg.Connection, data: dict) -> int:
    base_url = assert_allowed_source_url(data["base_url"])
    metadata = sanitize_metadata(data.get("metadata", {}))
    row = await conn.fetchrow(
        """
        INSERT INTO data_sources (
            source_code, source_name, source_type, authority_level,
            province_code, base_url, enabled, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (source_code) DO UPDATE SET
            source_name = EXCLUDED.source_name,
            source_type = EXCLUDED.source_type,
            authority_level = EXCLUDED.authority_level,
            province_code = EXCLUDED.province_code,
            base_url = EXCLUDED.base_url,
            enabled = EXCLUDED.enabled,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        data["source_code"],
        data["source_name"],
        data["source_type"],
        data["authority_level"],
        data.get("province_code"),
        base_url,
        data.get("enabled", True),
        json.dumps(metadata, ensure_ascii=False),
    )
    return row["id"]


async def find_data_source_by_code(conn: asyncpg.Connection, source_code: str) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM data_sources WHERE source_code = $1", source_code)


async def upsert_source_document(conn: asyncpg.Connection, data: dict) -> int:
    source_url = assert_allowed_source_url(data["source_url"])
    metadata = sanitize_metadata(data.get("metadata", {}))
    row = await conn.fetchrow(
        """
        INSERT INTO source_documents (
            data_source_id, source_url, title, publish_date, fetched_at,
            content_hash, content_type, storage_key, parser_name, parser_version, metadata
        )
        VALUES ($1, $2, $3, $4, COALESCE($5, NOW()), $6, $7, $8, $9, $10, $11)
        ON CONFLICT (data_source_id, source_url, content_hash) DO UPDATE SET
            title = EXCLUDED.title,
            publish_date = EXCLUDED.publish_date,
            fetched_at = EXCLUDED.fetched_at,
            content_type = EXCLUDED.content_type,
            storage_key = EXCLUDED.storage_key,
            parser_name = EXCLUDED.parser_name,
            parser_version = EXCLUDED.parser_version,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        data["data_source_id"],
        source_url,
        data.get("title"),
        data.get("publish_date"),
        data.get("fetched_at"),
        data["content_hash"],
        data.get("content_type"),
        data.get("storage_key"),
        data.get("parser_name"),
        data.get("parser_version"),
        json.dumps(metadata, ensure_ascii=False),
    )
    return row["id"]


async def insert_entity_evidence(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO entity_evidence (
            entity_type, entity_id, source_document_id,
            field_name, extracted_value_hash, confidence, quality_flags
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (entity_type, entity_id, source_document_id, field_name, extracted_value_hash) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            quality_flags = EXCLUDED.quality_flags
        RETURNING id
        """,
        data["entity_type"],
        data["entity_id"],
        data["source_document_id"],
        data.get("field_name"),
        data.get("extracted_value_hash"),
        data.get("confidence", 1.0),
        json.dumps(data.get("quality_flags", []), ensure_ascii=False),
    )
    return row["id"]
