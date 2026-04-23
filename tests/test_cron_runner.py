from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from gaokao_vault.config import AppConfig
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
    try:
        CronExpression.parse("0 14 * *")
    except ValueError as exc:
        assert "Expected 5 fields" in str(exc)
    else:
        raise AssertionError("CronExpression.parse() must reject non-5-field expressions")


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
