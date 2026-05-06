from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gaokao_vault.config import AppConfig, ScheduleConfig
from gaokao_vault.scheduler.cron_runner import CronExpression, IncrementalCronScheduler


def test_cron_expression_defaults_to_midnight_match() -> None:
    cron = CronExpression.parse("0 0 * * *")
    assert cron.matches(datetime(2026, 4, 23, 0, 0))
    assert not cron.matches(datetime(2026, 4, 23, 0, 1))


def test_cron_expression_supports_steps_and_lists() -> None:
    cron = CronExpression.parse("*/15 9,14 * * MON-FRI")
    assert cron.matches(datetime(2026, 4, 24, 9, 30))
    assert cron.matches(datetime(2026, 4, 24, 14, 45))
    assert not cron.matches(datetime(2026, 4, 25, 9, 30))


def test_cron_expression_rejects_invalid_field_count() -> None:
    with pytest.raises(ValueError, match="Expected 5 fields"):
        CronExpression.parse("0 14 * *")


def test_scheduler_skips_trigger_when_previous_run_is_active() -> None:
    scheduler = IncrementalCronScheduler(AppConfig())
    scheduler._cron = CronExpression.parse("* * * * *")
    scheduler._running_task = MagicMock(done=MagicMock(return_value=False))

    with patch.object(scheduler, "_run_incremental_crawl", new=AsyncMock()) as mock_run:
        asyncio.run(scheduler._maybe_trigger(datetime(2026, 4, 23, 14, 0)))

    mock_run.assert_not_called()


def test_scheduler_triggers_when_idle() -> None:
    scheduler = IncrementalCronScheduler(AppConfig())
    scheduler._cron = CronExpression.parse("* * * * *")

    async def _exercise() -> AsyncMock:
        with patch.object(scheduler, "_run_incremental_crawl", new=AsyncMock()) as mock_run:
            await scheduler._maybe_trigger(datetime(2026, 4, 23, 14, 0))
            assert scheduler._running_task is not None
            await scheduler._running_task
            return mock_run

    mock_run = asyncio.run(_exercise())
    mock_run.assert_awaited_once()


def test_scheduler_runs_configured_types_incrementally() -> None:
    config = AppConfig(schedule=ScheduleConfig(mode="incremental", types=["enrollment_plans", "special"]))
    scheduler = IncrementalCronScheduler(config)
    fake_pool = MagicMock()
    orchestrator = MagicMock()
    orchestrator.run_types = AsyncMock()
    orchestrator.run_independent = AsyncMock()
    orchestrator.run_all = AsyncMock()

    with (
        patch("gaokao_vault.db.connection.create_pool", new=AsyncMock(return_value=fake_pool)) as create_pool,
        patch("gaokao_vault.db.connection.close_pool", new=AsyncMock()) as close_pool,
        patch("gaokao_vault.db.queries.crawl_meta.fail_stale_running_tasks", new=AsyncMock(return_value=0)),
        patch("gaokao_vault.scheduler.orchestrator.Orchestrator", return_value=orchestrator) as orchestrator_cls,
    ):
        asyncio.run(scheduler._run_incremental_crawl(datetime(2026, 4, 23, 14, 0)))

    create_pool.assert_awaited_once_with(config.db)
    orchestrator_cls.assert_called_once()
    assert orchestrator_cls.call_args.kwargs["mode"] == "incremental"
    orchestrator.run_independent.assert_awaited_once_with(["enrollment_plans", "special"], max_concurrent=3)
    orchestrator.run_types.assert_not_called()
    orchestrator.run_all.assert_not_called()
    close_pool.assert_awaited_once()


def test_scheduler_runs_all_types_with_phase_order_by_default() -> None:
    config = AppConfig()
    scheduler = IncrementalCronScheduler(config)
    fake_pool = MagicMock()
    orchestrator = MagicMock()
    orchestrator.run_types = AsyncMock()
    orchestrator.run_independent = AsyncMock()
    orchestrator.run_all = AsyncMock()

    with (
        patch("gaokao_vault.db.connection.create_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.db.connection.close_pool", new=AsyncMock()),
        patch("gaokao_vault.db.queries.crawl_meta.fail_stale_running_tasks", new=AsyncMock(return_value=0)),
        patch("gaokao_vault.scheduler.orchestrator.Orchestrator", return_value=orchestrator),
    ):
        asyncio.run(scheduler._run_incremental_crawl(datetime(2026, 4, 23, 14, 0)))

    orchestrator.run_all.assert_awaited_once()
    orchestrator.run_independent.assert_not_called()
    orchestrator.run_types.assert_not_called()


def test_scheduler_recovers_stale_running_tasks_before_default_crawl() -> None:
    config = AppConfig()
    scheduler = IncrementalCronScheduler(config)
    fake_pool = MagicMock()
    orchestrator = MagicMock()
    orchestrator.run_all = AsyncMock()

    with (
        patch("gaokao_vault.db.connection.create_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.db.connection.close_pool", new=AsyncMock()),
        patch(
            "gaokao_vault.db.queries.crawl_meta.fail_stale_running_tasks",
            new=AsyncMock(return_value=2),
        ) as fail_stale,
        patch("gaokao_vault.scheduler.orchestrator.Orchestrator", return_value=orchestrator),
    ):
        asyncio.run(scheduler._run_incremental_crawl(datetime(2026, 4, 23, 14, 0)))

    fail_stale.assert_awaited_once_with(fake_pool, stale_after_seconds=config.crawl.spider_timeout)
