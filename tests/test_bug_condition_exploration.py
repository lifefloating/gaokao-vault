"""Bug Condition Exploration Test — Cross-Loop asyncpg Pool Usage.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

This test encodes the EXPECTED post-fix behavior:
  - BaseGaokaoSpider._get_pool() creates a pool bound to the CURRENT event loop.
  - process_item() and on_close() complete without event-loop errors when
    the spider callbacks run inside a *different* loop than the one the
    Orchestrator (main loop) uses.

On UNFIXED code the test MUST FAIL because:
  - BaseGaokaoSpider stores a pre-created db_pool from __init__ and has no
    _get_pool() method, so cross-loop usage raises RuntimeError /
    ConnectionDoesNotExistError / InterfaceError.

After the fix the test MUST PASS because:
  - _get_pool() lazily creates a local asyncpg.Pool on the current loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.base import BaseGaokaoSpider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_config() -> DatabaseConfig:
    """Return a DatabaseConfig suitable for testing (no real DB needed)."""
    return DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )


def _make_mock_pool() -> MagicMock:
    """Create a mock that quacks like asyncpg.Pool."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    # pool.acquire() used as async context manager
    acm = AsyncMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acm
    pool.close = AsyncMock()
    return pool


def _run_in_new_loop(coro_fn):
    """Run *coro_fn* (a zero-arg async callable) on a brand-new event loop
    in a separate thread — simulating what scrapling's Spider.start() does
    via anyio.run().

    Returns the result or raises the exception from the coroutine.
    """
    result_box: dict[str, Any] = {}

    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box["value"] = loop.run_until_complete(coro_fn())
        except BaseException as exc:
            result_box["error"] = exc
        finally:
            loop.close()

    t = threading.Thread(target=_thread_target)
    t.start()
    t.join(timeout=30)

    if "error" in result_box:
        raise result_box["error"]
    return result_box.get("value")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

entity_types_st = st.sampled_from([
    "schools",
    "majors",
    "score_lines",
    "timelines",
    "school_majors",
    "enrollment_plans",
    "charters",
    "special",
])

item_st = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=50),
    "value": st.integers(min_value=0, max_value=10000),
})

unique_keys_st = st.fixed_dictionaries({
    "sch_id": st.integers(min_value=1, max_value=99999),
})

stats_st = st.fixed_dictionaries({
    "new": st.integers(min_value=0, max_value=100),
    "updated": st.integers(min_value=0, max_value=100),
    "unchanged": st.integers(min_value=0, max_value=100),
    "failed": st.integers(min_value=0, max_value=100),
})


# ---------------------------------------------------------------------------
# Property 1: Bug Condition — Cross-Loop asyncpg Pool Usage Crashes Spider
# ---------------------------------------------------------------------------


class TestBugConditionCrossLoopPoolUsage:
    """Property 1: Bug Condition - Cross-Loop asyncpg Pool Usage Crashes
    Spider Callbacks.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

    The expected (post-fix) behaviour is that BaseGaokaoSpider lazily creates
    a local pool via _get_pool() on the current event loop, so process_item()
    and on_close() succeed even when invoked from a different loop.

    On UNFIXED code this test FAILS because _get_pool() does not exist and
    the spider uses the main-loop pool directly.
    """

    # ---- structural check: _get_pool must exist after fix ----

    def test_spider_has_get_pool_method(self):
        """After fix, BaseGaokaoSpider must expose an async _get_pool()
        method that lazily creates a loop-local pool."""
        assert hasattr(BaseGaokaoSpider, "_get_pool"), (
            "BaseGaokaoSpider is missing _get_pool(); the spider still uses "
            "a pre-created db_pool from __init__ — cross-loop usage will crash."
        )

    def test_spider_accepts_db_config(self):
        """After fix, BaseGaokaoSpider.__init__ must accept db_config
        (DatabaseConfig) instead of db_pool (asyncpg.Pool)."""
        import inspect

        sig = inspect.signature(BaseGaokaoSpider.__init__)
        params = list(sig.parameters.keys())
        assert "db_config" in params, (
            "BaseGaokaoSpider.__init__ still requires db_pool instead of "
            "db_config — the pool will be bound to the wrong event loop."
        )
        assert "db_pool" not in params, (
            "BaseGaokaoSpider.__init__ still accepts db_pool — this causes "
            "cross-loop errors when scrapling creates its own event loop."
        )

    # ---- process_item from a different loop ----

    @given(
        entity_type=entity_types_st,
        item=item_st,
        unique_keys=unique_keys_st,
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_process_item_from_different_loop(self, entity_type: str, item: dict, unique_keys: dict):
        """**Validates: Requirements 1.2**

        After fix, process_item() called from a different event loop must
        complete without RuntimeError / ConnectionDoesNotExistError /
        InterfaceError because _get_pool() creates a local pool on the
        current loop.
        """
        db_config = _make_db_config()
        mock_pool = _make_mock_pool()

        with (
            patch(
                "gaokao_vault.spiders.base.create_local_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
            patch(
                "gaokao_vault.spiders.base.deduplicate_and_persist",
                new=AsyncMock(return_value="new"),
            ),
        ):
            # Construct spider — after fix this uses db_config, not db_pool
            spider = BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)

            async def _call():
                return await spider.process_item(
                    item=item,
                    entity_type=entity_type,
                    unique_keys=unique_keys,
                )

            # Run from a DIFFERENT event loop (simulating scrapling's loop)
            result = _run_in_new_loop(_call)
            assert result in ("new", "updated", "unchanged", "failed")

    # ---- on_close from a different loop ----

    @given(stats=stats_st)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_on_close_from_different_loop(self, stats: dict):
        """**Validates: Requirements 1.1**

        After fix, on_close() called from a different event loop must
        complete without RuntimeError because _get_pool() creates a local
        pool on the current loop.
        """
        db_config = _make_db_config()
        mock_pool = _make_mock_pool()

        with (
            patch(
                "gaokao_vault.spiders.base.create_local_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
            patch(
                "gaokao_vault.db.queries.crawl_meta.update_task_stats",
                new=AsyncMock(return_value=None),
            ),
        ):
            spider = BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)
            spider._stats = dict(stats)

            async def _call():
                await spider.on_close()

            # Run from a DIFFERENT event loop
            _run_in_new_loop(_call)

    # ---- concurrent cross-loop calls ----

    def test_concurrent_process_item_from_different_loop(self):
        """**Validates: Requirements 1.3**

        After fix, multiple concurrent process_item() calls from a different
        loop must all succeed without InterfaceError.
        """
        db_config = _make_db_config()
        mock_pool = _make_mock_pool()

        with (
            patch(
                "gaokao_vault.spiders.base.create_local_pool",
                new=AsyncMock(return_value=mock_pool),
            ),
            patch(
                "gaokao_vault.spiders.base.deduplicate_and_persist",
                new=AsyncMock(return_value="new"),
            ),
        ):
            spider = BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)

            async def _concurrent_calls():
                tasks = [
                    spider.process_item(
                        item={"name": f"school_{i}", "value": i},
                        entity_type="schools",
                        unique_keys={"sch_id": i},
                    )
                    for i in range(5)
                ]
                results = await asyncio.gather(*tasks)
                return results

            results = _run_in_new_loop(_concurrent_calls)
            assert all(r in ("new", "updated", "unchanged", "failed") for r in results)

    # ---- all spider types affected ----

    def test_all_spider_types_use_db_config(self):
        """**Validates: Requirements 1.4**

        After fix, all spider subclasses must accept db_config (not db_pool)
        because they all inherit from BaseGaokaoSpider.
        """
        import inspect

        from gaokao_vault.scheduler.orchestrator import SPIDER_MAP

        for task_type, spider_cls in SPIDER_MAP.items():
            sig = inspect.signature(spider_cls.__init__)
            params = list(sig.parameters.keys())
            assert "db_pool" not in params, (
                f"{spider_cls.__name__} (task_type={task_type}) still accepts db_pool — cross-loop errors will occur."
            )
