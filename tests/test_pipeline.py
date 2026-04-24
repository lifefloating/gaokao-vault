"""Tests for the data pipeline: hasher, validator, and dedup logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from gaokao_vault.models.school import SchoolItem
from gaokao_vault.models.score import ScoreLineItem
from gaokao_vault.pipeline.dedup import deduplicate_and_persist
from gaokao_vault.pipeline.hasher import compute_content_hash
from gaokao_vault.pipeline.validator import validate_item


def _make_mock_pool_and_conn() -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()
    conn = AsyncMock()

    acquire_context = AsyncMock()
    acquire_context.__aenter__ = AsyncMock(return_value=conn)
    acquire_context.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire_context
    return pool, conn


class TestContentHash:
    def test_deterministic(self):
        item = {"name": "Test School", "sch_id": 1, "city": "Beijing"}
        h1 = compute_content_hash(item)
        h2 = compute_content_hash(item)
        assert h1 == h2

    def test_excludes_meta_fields(self):
        item1 = {"name": "Test", "sch_id": 1}
        item2 = {"name": "Test", "sch_id": 1, "id": 99, "created_at": "2024-01-01", "content_hash": "abc"}
        assert compute_content_hash(item1) == compute_content_hash(item2)

    def test_different_content_different_hash(self):
        item1 = {"name": "School A", "sch_id": 1}
        item2 = {"name": "School B", "sch_id": 1}
        assert compute_content_hash(item1) != compute_content_hash(item2)

    def test_key_order_independent(self):
        item1 = {"name": "Test", "sch_id": 1, "city": "Beijing"}
        item2 = {"city": "Beijing", "sch_id": 1, "name": "Test"}
        assert compute_content_hash(item1) == compute_content_hash(item2)


class TestValidator:
    def test_valid_school_item(self):
        data = {"sch_id": 1, "name": "Test University"}
        result = validate_item(SchoolItem, data)
        assert result is not None
        assert result["sch_id"] == 1
        assert result["name"] == "Test University"
        assert result["is_211"] is False

    def test_invalid_school_item_missing_required(self):
        data = {"sch_id": 1}  # missing 'name'
        result = validate_item(SchoolItem, data)
        assert result is None

    def test_valid_score_line(self):
        data = {
            "province_id": 1,
            "year": 2024,
            "batch": "本科一批",
            "score": 530,
        }
        result = validate_item(ScoreLineItem, data)
        assert result is not None
        assert result["year"] == 2024

    def test_invalid_score_line_year(self):
        data = {
            "province_id": 1,
            "year": 1999,  # below 2000 minimum
            "batch": "本科一批",
        }
        result = validate_item(ScoreLineItem, data)
        assert result is None

    def test_school_defaults(self):
        data = {"sch_id": 42, "name": "Test U"}
        result = validate_item(SchoolItem, data)
        assert result is not None
        assert result["is_985"] is False
        assert result["is_double_first"] is False
        assert result["province_id"] is None


class TestDedupPersistence:
    def test_persists_within_transaction(self):
        pool, conn = _make_mock_pool_and_conn()

        transaction_context = AsyncMock()
        transaction_context.__aenter__ = AsyncMock(return_value=None)
        transaction_context.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=transaction_context)

        async def fetchrow_side_effect(query, *args):
            if "SELECT id, content_hash" in query:
                return None
            if "crawl_snapshots" in query:
                return {"id": 1}
            return None

        conn.fetchrow.side_effect = fetchrow_side_effect
        upsert_fn = AsyncMock(return_value=123)

        result = asyncio.run(
            deduplicate_and_persist(
                db_pool=pool,
                entity_type="schools",
                item={"sch_id": 1, "name": "Test"},
                content_hash="abc",
                unique_keys={"sch_id": 1},
                crawl_task_id=1,
                upsert_fn=upsert_fn,
            )
        )

        assert result == "new"
        conn.transaction.assert_called_once_with()
        transaction_context.__aenter__.assert_awaited_once_with()
        transaction_context.__aexit__.assert_awaited_once()

    def test_rejects_upsert_returning_invalid_entity_id(self):
        pool, conn = _make_mock_pool_and_conn()

        transaction_context = AsyncMock()
        transaction_context.__aenter__ = AsyncMock(return_value=None)
        transaction_context.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=transaction_context)
        conn.fetchrow.return_value = None

        result = asyncio.run(
            deduplicate_and_persist(
                db_pool=pool,
                entity_type="schools",
                item={"sch_id": 1, "name": "Test"},
                content_hash="abc",
                unique_keys={"sch_id": 1},
                crawl_task_id=1,
                upsert_fn=AsyncMock(return_value=0),
            )
        )

        assert result == "failed"
