from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

from gaokao_vault.db.queries.sources import (
    find_data_source_by_code,
    insert_entity_evidence,
    upsert_data_source,
    upsert_source_document,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.row: dict[str, object] = {"id": 101}

    async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
        self.query = query
        self.args = args
        return self.row


def test_upsert_data_source_uses_source_code_conflict_and_json_metadata() -> None:
    conn = _FakeConnection()

    source_id = asyncio.run(
        upsert_data_source(
            cast(Any, conn),
            {
                "source_code": "gaokao_chsi",
                "source_name": "阳光高考",
                "source_type": "official",
                "authority_level": 95,
                "province_code": None,
                "base_url": "https://gaokao.chsi.com.cn",
                "enabled": True,
                "metadata": {"lang": "zh-CN", "tier": 1},
            },
        )
    )

    assert source_id == 101
    assert "ON CONFLICT (source_code) DO UPDATE SET" in conn.query
    assert "source_name = EXCLUDED.source_name" in conn.query
    assert "metadata = EXCLUDED.metadata" in conn.query
    assert conn.args[-1] == json.dumps({"lang": "zh-CN", "tier": 1}, ensure_ascii=False)


def test_upsert_data_source_rejects_private_base_url() -> None:
    conn = _FakeConnection()

    with pytest.raises(ValueError):
        asyncio.run(
            upsert_data_source(
                cast(Any, conn),
                {
                    "source_code": "bad",
                    "source_name": "Bad",
                    "source_type": "official",
                    "authority_level": 1,
                    "base_url": "http://127.0.0.1/admin",
                },
            )
        )


def test_upsert_data_source_sanitizes_metadata_before_persisting() -> None:
    conn = _FakeConnection()

    asyncio.run(
        upsert_data_source(
            cast(Any, conn),
            {
                "source_code": "safe",
                "source_name": "Safe",
                "source_type": "official",
                "authority_level": 80,
                "base_url": "https://example.edu",
                "metadata": {
                    "x_api_key": "secret123",
                    "public": "招生计划 token=abc123",
                },
            },
        )
    )

    assert conn.args[-1] == json.dumps({"public": "招生计划 [REDACTED]"}, ensure_ascii=False)


def test_find_data_source_by_code_uses_exact_code_lookup() -> None:
    conn = _FakeConnection()
    conn.row = {"id": 3, "source_code": "prov_jy", "source_name": "省教育厅"}

    row = asyncio.run(find_data_source_by_code(cast(Any, conn), "prov_jy"))

    assert row == {"id": 3, "source_code": "prov_jy", "source_name": "省教育厅"}
    assert "FROM data_sources WHERE source_code = $1" in conn.query
    assert conn.args == ("prov_jy",)


def test_upsert_source_document_uses_conflict_key_and_coalesces_fetched_at() -> None:
    conn = _FakeConnection()

    document_id = asyncio.run(
        upsert_source_document(
            cast(Any, conn),
            {
                "data_source_id": 8,
                "source_url": "https://example.edu/a.html",
                "title": "招生计划",
                "publish_date": None,
                "fetched_at": None,
                "content_hash": "a" * 64,
                "content_type": "text/html",
                "storage_key": "raw/a.html",
                "parser_name": "html_parser",
                "parser_version": "v1",
                "metadata": {"encoding": "utf-8"},
            },
        )
    )

    assert document_id == 101
    assert "ON CONFLICT (data_source_id, source_url, content_hash) DO UPDATE SET" in conn.query
    assert "COALESCE($5, NOW())" in conn.query
    assert conn.args[4] is None
    assert conn.args[-1] == json.dumps({"encoding": "utf-8"}, ensure_ascii=False)


def test_upsert_source_document_rejects_private_source_url() -> None:
    conn = _FakeConnection()

    with pytest.raises(ValueError):
        asyncio.run(
            upsert_source_document(
                cast(Any, conn),
                {
                    "data_source_id": 8,
                    "source_url": "http://localtest.me/admin",
                    "content_hash": "a" * 64,
                },
            )
        )


def test_upsert_source_document_sanitizes_metadata_before_persisting() -> None:
    conn = _FakeConnection()

    asyncio.run(
        upsert_source_document(
            cast(Any, conn),
            {
                "data_source_id": 8,
                "source_url": "https://example.edu/a.html",
                "content_hash": "a" * 64,
                "metadata": {"set_cookie": "session=abc", "title": "<b>招生计划</b>"},
            },
        )
    )

    assert conn.args[-1] == json.dumps({"title": "招生计划"}, ensure_ascii=False)


def test_insert_entity_evidence_uses_natural_key_conflict_and_json_quality_flags() -> None:
    conn = _FakeConnection()

    evidence_id = asyncio.run(
        insert_entity_evidence(
            cast(Any, conn),
            {
                "entity_type": "school",
                "entity_id": 12,
                "source_document_id": 9,
                "field_name": "name",
                "extracted_value_hash": "b" * 64,
                "confidence": 0.86,
                "quality_flags": ["ocr_review", "manual_spot_check"],
            },
        )
    )

    assert evidence_id == 101
    assert "ON CONFLICT (entity_type, entity_id, source_document_id, field_name, extracted_value_hash)" in conn.query
    assert "confidence = EXCLUDED.confidence" in conn.query
    assert "quality_flags = EXCLUDED.quality_flags" in conn.query
    assert conn.args[-1] == json.dumps(["ocr_review", "manual_spot_check"], ensure_ascii=False)


def test_source_document_hash_uses_public_source_fields() -> None:
    from gaokao_vault.pipeline.hasher import compute_content_hash

    item = {"source_url": "https://example.edu/a.html", "title": "招生计划", "cookie": "secret"}
    digest = compute_content_hash(item, exclude_fields={"cookie"})

    assert len(digest) == 64
