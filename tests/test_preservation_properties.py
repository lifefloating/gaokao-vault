"""Preservation Property Tests — Dedup Classification and Stats Update Logic Unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

These tests verify that existing behaviour is preserved BEFORE the fix is applied.
They run against the UNFIXED code using mocked DB layers (no real PostgreSQL needed).

EXPECTED OUTCOME: All tests PASS on unfixed code, confirming baseline behaviour.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gaokao_vault.constants import PHASE2_TYPES, PHASE3_TYPES, TaskType
from gaokao_vault.db.queries.crawl_meta import update_task_stats
from gaokao_vault.pipeline.dedup import TABLE_MAP, deduplicate_and_persist
from gaokao_vault.spiders.base import BaseGaokaoSpider

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Entity types that have TABLE_MAP entries (so find_latest_hash works)
entity_types_with_mapping_st = st.sampled_from(list(TABLE_MAP.keys()))

content_hash_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
    min_size=8,
    max_size=64,
)

stats_st = st.fixed_dictionaries({
    "new": st.integers(min_value=0, max_value=500),
    "updated": st.integers(min_value=0, max_value=500),
    "unchanged": st.integers(min_value=0, max_value=500),
    "failed": st.integers(min_value=0, max_value=500),
})

optional_error_st = st.one_of(st.none(), st.text(min_size=1, max_size=100))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pool_and_conn() -> tuple[MagicMock, AsyncMock]:
    """Return (pool, conn) mocks wired so pool.acquire() yields conn."""
    pool = MagicMock()
    conn = AsyncMock()

    transaction_context = AsyncMock()
    transaction_context.__aenter__ = AsyncMock(return_value=None)
    transaction_context.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=transaction_context)

    acm = AsyncMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acm
    return pool, conn


def _unique_keys_for(entity_type: str) -> dict[str, Any]:
    """Build a minimal unique_keys dict that satisfies TABLE_MAP for *entity_type*."""
    _, _, key_fields = TABLE_MAP[entity_type]
    keys: dict[str, Any] = {}
    for f in key_fields:
        if "id" in f or "year" in f:
            keys[f] = 1
        else:
            keys[f] = "test_value"
    return keys


# ---------------------------------------------------------------------------
# Property 2a: Dedup Classification — new / unchanged / updated
# **Validates: Requirements 3.1**
# ---------------------------------------------------------------------------


class TestDedupClassificationPreservation:
    """For all valid (entity_type, item, content_hash, unique_keys) combinations,
    deduplicate_and_persist returns the correct new/updated/unchanged
    classification based on whether an existing record and hash match.
    """

    @given(
        entity_type=entity_types_with_mapping_st,
        content_hash=content_hash_st,
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_new_item_classification(self, entity_type: str, content_hash: str):
        """**Validates: Requirements 3.1**

        When find_latest_hash returns (None, None), the item is NEW.
        deduplicate_and_persist must return "new".
        """
        pool, conn = _make_mock_pool_and_conn()
        unique_keys = _unique_keys_for(entity_type)
        item = {"name": "test", "value": 42}
        upsert_fn = AsyncMock(return_value=100)  # returns entity_id

        # No existing record
        conn.fetchrow.return_value = None  # find_latest_hash → (None, None)

        # insert_snapshot mock
        snapshot_row = MagicMock()
        snapshot_row.__getitem__ = lambda self, k: 1 if k == "id" else None

        call_count = 0

        async def _fetchrow_side_effect(query, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # find_latest_hash: no existing record
                return None
            # insert_snapshot RETURNING id
            return {"id": 1}

        conn.fetchrow.side_effect = _fetchrow_side_effect

        result = asyncio.run(
            deduplicate_and_persist(
                db_pool=pool,
                entity_type=entity_type,
                item=item,
                content_hash=content_hash,
                unique_keys=unique_keys,
                crawl_task_id=1,
                upsert_fn=upsert_fn,
            )
        )
        assert result == "new"

    @given(
        entity_type=entity_types_with_mapping_st,
        content_hash=content_hash_st,
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_unchanged_item_classification(self, entity_type: str, content_hash: str):
        """**Validates: Requirements 3.1**

        When find_latest_hash returns (existing_id, same_hash),
        deduplicate_and_persist must return "unchanged".
        """
        pool, conn = _make_mock_pool_and_conn()
        unique_keys = _unique_keys_for(entity_type)
        item = {"name": "test", "value": 42}

        call_count = 0

        async def _fetchrow_side_effect(query, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # find_latest_hash: existing record with SAME hash
                return {"id": 50, "content_hash": content_hash}
            # insert_snapshot RETURNING id
            return {"id": 1}

        conn.fetchrow.side_effect = _fetchrow_side_effect

        result = asyncio.run(
            deduplicate_and_persist(
                db_pool=pool,
                entity_type=entity_type,
                item=item,
                content_hash=content_hash,
                unique_keys=unique_keys,
                crawl_task_id=1,
            )
        )
        assert result == "unchanged"

    @given(
        entity_type=entity_types_with_mapping_st,
        content_hash=content_hash_st,
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_updated_item_classification(self, entity_type: str, content_hash: str):
        """**Validates: Requirements 3.1**

        When find_latest_hash returns (existing_id, different_hash),
        deduplicate_and_persist must return "updated".
        """
        pool, conn = _make_mock_pool_and_conn()
        unique_keys = _unique_keys_for(entity_type)
        item = {"name": "test", "value": 42}
        upsert_fn = AsyncMock(return_value=50)

        different_hash = content_hash + "_old"
        call_count = 0

        async def _fetchrow_side_effect(query, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # find_latest_hash: existing record with DIFFERENT hash
                return {"id": 50, "content_hash": different_hash}
            if call_count == 2:
                # SELECT * FROM table WHERE id = $1 (old data for snapshot)
                return {"id": 50, "name": "old_value"}
            # insert_snapshot RETURNING id
            return {"id": 1}

        conn.fetchrow.side_effect = _fetchrow_side_effect

        result = asyncio.run(
            deduplicate_and_persist(
                db_pool=pool,
                entity_type=entity_type,
                item=item,
                content_hash=content_hash,
                unique_keys=unique_keys,
                crawl_task_id=1,
                upsert_fn=upsert_fn,
            )
        )
        assert result == "updated"


# ---------------------------------------------------------------------------
# Property 2b: Stats Update — correct status, totals, and counts
# **Validates: Requirements 3.2**
# ---------------------------------------------------------------------------


class TestStatsUpdatePreservation:
    """For all valid _stats dicts, update_task_stats persists correct
    status, total_items, new_items, updated_items, unchanged_items,
    failed_items, and error_message.
    """

    @given(stats=stats_st, error=optional_error_st)
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_stats_update_values(self, stats: dict[str, int], error: str | None):
        """**Validates: Requirements 3.2**

        update_task_stats must compute:
        - status = "failed" if error else "success"
        - total = new + updated + unchanged + failed
        - pass correct individual counts
        """
        pool, conn = _make_mock_pool_and_conn()
        conn.execute = AsyncMock(return_value=None)

        task_id = 42

        asyncio.run(update_task_stats(pool, task_id, stats, error))

        # Verify conn.execute was called with correct args
        conn.execute.assert_awaited_once()
        call_args = conn.execute.call_args

        # Positional args: (query, task_id, status, total, new, updated, unchanged, failed, error)
        args = call_args[0]
        _query = args[0]
        passed_task_id = args[1]
        passed_status = args[2]
        passed_total = args[3]
        passed_new = args[4]
        passed_updated = args[5]
        passed_unchanged = args[6]
        passed_failed = args[7]
        passed_error = args[8]

        expected_status = "failed" if error else "success"
        expected_total = stats["new"] + stats["updated"] + stats["unchanged"] + stats["failed"]

        assert passed_task_id == task_id
        assert passed_status == expected_status
        assert passed_total == expected_total
        assert passed_new == stats["new"]
        assert passed_updated == stats["updated"]
        assert passed_unchanged == stats["unchanged"]
        assert passed_failed == stats["failed"]
        assert passed_error == error


# ---------------------------------------------------------------------------
# Property 2c: Phase Ordering — Phase 2 before Phase 3
# **Validates: Requirements 3.3**
# ---------------------------------------------------------------------------


class TestPhaseOrderingPreservation:
    """Orchestrator.run_all() must run Phase 2 types before Phase 3 types."""

    def test_phase2_and_phase3_are_disjoint(self):
        """**Validates: Requirements 3.3**

        PHASE2_TYPES and PHASE3_TYPES must not overlap.
        """
        phase2_set = set(PHASE2_TYPES)
        phase3_set = set(PHASE3_TYPES)
        assert phase2_set.isdisjoint(phase3_set), f"Overlap: {phase2_set & phase3_set}"

    def test_phase2_types_are_core_entities(self):
        """**Validates: Requirements 3.3**

        Phase 2 must contain the core entity types.
        """
        expected = {
            TaskType.SCHOOLS,
            TaskType.MAJORS,
            TaskType.SCORE_LINES,
            TaskType.TIMELINES,
        }
        assert set(PHASE2_TYPES) == expected

    def test_phase3_types_are_associations(self):
        """**Validates: Requirements 3.3**

        Phase 3 must contain the association/dependent types.
        """
        expected = {
            TaskType.SCHOOL_MAJORS,
            TaskType.SCORE_SEGMENTS,
            TaskType.ENROLLMENT_PLANS,
            TaskType.MAJOR_ADMISSION_RESULTS,
            TaskType.CHARTERS,
            TaskType.SPECIAL,
            TaskType.SCHOOL_SATISFACTION,
            TaskType.MAJOR_SATISFACTION,
            TaskType.INTERPRETATIONS,
        }
        assert set(PHASE3_TYPES) == expected

    def test_run_all_calls_phases_in_order(self):
        """**Validates: Requirements 3.3**

        Orchestrator.run_all() must call _run_phase with Phase 2 types
        first, then Phase 3 types.
        """
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        mock_pool = MagicMock()
        orch = Orchestrator(db_pool=mock_pool, mode="full")

        phase_calls: list[list[str]] = []

        async def _mock_run_phase(task_types: list[str]):
            phase_calls.append(task_types)
            return [{"new": 1, "updated": 0, "unchanged": 0, "failed": 0}]

        orch._run_phase = _mock_run_phase  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        asyncio.run(orch.run_all())

        assert len(phase_calls) == 2
        assert phase_calls[0] == [t.value for t in PHASE2_TYPES]
        assert phase_calls[1] == [t.value for t in PHASE3_TYPES]

    def test_run_all_skips_phase3_when_phase2_has_failures(self):
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        mock_pool = MagicMock()
        orch = Orchestrator(db_pool=mock_pool, mode="full")

        phase_calls: list[list[str]] = []

        async def _mock_run_phase(task_types: list[str]):
            phase_calls.append(task_types)
            if task_types == [t.value for t in PHASE2_TYPES]:
                return [{"new": 1, "updated": 0, "unchanged": 0, "failed": 0}, {"failed": 1}]
            return [{"new": 1, "updated": 0, "unchanged": 0, "failed": 0}]

        orch._run_phase = _mock_run_phase  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        asyncio.run(orch.run_all())

        assert len(phase_calls) == 1
        assert phase_calls[0] == [t.value for t in PHASE2_TYPES]

    def test_phase_summary_treats_non_dict_results_as_unstable(self):
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        stable, failed, total = Orchestrator._phase_summary([{"failed": 0}, None, RuntimeError("boom")])

        assert stable is False
        assert failed == 2
        assert total == 3


# ---------------------------------------------------------------------------
# Property 2d: Spider Exception Handling
# **Validates: Requirements 3.4**
# ---------------------------------------------------------------------------


class TestSpiderExceptionHandlingPreservation:
    """Exceptions in process_item are caught, logged, and increment failed count."""

    def test_process_item_catches_dedup_exception(self):
        """**Validates: Requirements 3.4**

        When deduplicate_and_persist raises an exception, process_item must
        catch it, increment _stats["failed"], and return "failed".
        """
        from gaokao_vault.config import DatabaseConfig

        db_config = DatabaseConfig(
            dsn="postgresql://test:test@localhost:5432/test_db",
            pool_min=1,
            pool_max=2,
        )
        spider = BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)
        spider._get_pool = AsyncMock(return_value=MagicMock())  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        with patch(
            "gaokao_vault.spiders.base.deduplicate_and_persist",
            new=AsyncMock(side_effect=RuntimeError("DB error")),
        ):
            result = asyncio.run(
                spider.process_item(
                    item={"name": "test"},
                    entity_type="schools",
                    unique_keys={"sch_id": 1},
                )
            )

        assert result == "failed"
        assert spider._stats["failed"] == 1

    def test_process_item_increments_correct_stat_on_success(self):
        """**Validates: Requirements 3.4**

        When deduplicate_and_persist succeeds, process_item must increment
        the correct stat counter.
        """
        from gaokao_vault.config import DatabaseConfig

        db_config = DatabaseConfig(
            dsn="postgresql://test:test@localhost:5432/test_db",
            pool_min=1,
            pool_max=2,
        )
        spider = BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)
        spider._get_pool = AsyncMock(return_value=MagicMock())  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        for change_type in ("new", "updated", "unchanged"):
            spider._stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}

            with patch(
                "gaokao_vault.spiders.base.deduplicate_and_persist",
                new=AsyncMock(return_value=change_type),
            ):
                result = asyncio.run(
                    spider.process_item(
                        item={"name": "test"},
                        entity_type="schools",
                        unique_keys={"sch_id": 1},
                    )
                )

            assert result == change_type
            assert spider._stats[change_type] == 1

    def test_orchestrator_run_single_catches_spider_exception(self):
        """**Validates: Requirements 3.4**

        When a spider raises an exception during run_single, the orchestrator
        catches it, logs it, and records failure via task_manager.finish_task.
        """
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        mock_pool = MagicMock()
        orch = Orchestrator(db_pool=mock_pool, mode="full")

        # Mock task_manager
        orch.task_manager = MagicMock()
        orch.task_manager.start_task = AsyncMock(return_value=99)
        orch.task_manager.finish_task = AsyncMock()

        # Make spider construction raise
        with patch(
            "gaokao_vault.scheduler.orchestrator.SPIDER_MAP",
            {"schools": MagicMock(side_effect=RuntimeError("Spider init failed"))},
        ):
            stats = asyncio.run(orch.run_single("schools"))

        assert stats["failed"] == 1
        orch.task_manager.finish_task.assert_awaited_once()
        # Verify error was passed
        call_args = orch.task_manager.finish_task.call_args
        assert call_args[1].get("error") is not None or (len(call_args[0]) >= 3 and call_args[0][2] is not None)


# ---------------------------------------------------------------------------
# Property 2e: create_pool() Singleton Behaviour
# **Validates: Requirements 3.5**
# ---------------------------------------------------------------------------


class TestCreatePoolSingletonPreservation:
    """create_pool() must return a singleton pool."""

    def test_create_pool_returns_same_instance(self):
        """**Validates: Requirements 3.5**

        Calling create_pool() twice must return the same pool instance.
        """
        import gaokao_vault.db.connection as conn_mod

        mock_pool = MagicMock()

        # Save original state
        original_pool = conn_mod._pool

        try:
            # Reset singleton
            conn_mod._pool = None

            mock_create = AsyncMock(return_value=mock_pool)
            with patch("asyncpg.create_pool", new=mock_create):
                from gaokao_vault.config import DatabaseConfig
                from gaokao_vault.db.connection import create_pool

                config = DatabaseConfig(
                    dsn="postgresql://test:test@localhost:5432/test_db",
                    pool_min=1,
                    pool_max=2,
                )

                async def _run() -> tuple:
                    p1 = await create_pool(config)
                    p2 = await create_pool(config)
                    return p1, p2

                pool1, pool2 = asyncio.run(_run())

                assert pool1 is pool2
                # asyncpg.create_pool must only be called once (singleton)
                assert mock_create.call_count == 1
        finally:
            conn_mod._pool = original_pool

    def test_create_pool_singleton_reset_on_close(self):
        """**Validates: Requirements 3.5**

        After close_pool(), the singleton is cleared and create_pool()
        creates a new pool.
        """
        import gaokao_vault.db.connection as conn_mod

        mock_pool1 = MagicMock()
        mock_pool1.close = AsyncMock()
        mock_pool2 = MagicMock()
        mock_pool2.close = AsyncMock()

        original_pool = conn_mod._pool

        try:
            conn_mod._pool = None

            call_count = 0

            async def _mock_create_pool(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_pool1 if call_count == 1 else mock_pool2

            with patch("asyncpg.create_pool", new=_mock_create_pool):
                from gaokao_vault.config import DatabaseConfig
                from gaokao_vault.db.connection import close_pool, create_pool

                config = DatabaseConfig(
                    dsn="postgresql://test:test@localhost:5432/test_db",
                    pool_min=1,
                    pool_max=2,
                )

                async def _run() -> tuple:
                    p1 = await create_pool(config)
                    assert p1 is mock_pool1

                    await close_pool()
                    assert conn_mod._pool is None

                    p2 = await create_pool(config)
                    return p1, p2

                p1, p2 = asyncio.run(_run())
                assert p2 is mock_pool2
                assert p1 is not p2
        finally:
            conn_mod._pool = original_pool
