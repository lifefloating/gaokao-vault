from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from gaokao_vault.config import CrawlConfig
from gaokao_vault.scheduler.orchestrator import Orchestrator

NO_ACTIVE_CRAWL_MESSAGE = "No active crawl to stop"


class _PausableTimeoutSpider:
    name = "pausable_timeout_spider"

    def __init__(self, **_kwargs) -> None:
        self._stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
        self._stop_event: asyncio.Event | None = None
        self.active = False
        self.pause_called_while_active = False

    async def stream(self):
        self._stop_event = asyncio.Event()
        self.active = True
        try:
            await self._stop_event.wait()
        finally:
            self.active = False

        if False:
            yield None

    def pause(self) -> None:
        self.pause_called_while_active = self.active
        if self._stop_event is None or not self.active:
            raise RuntimeError(NO_ACTIVE_CRAWL_MESSAGE)
        self._stop_event.set()


def test_run_single_pauses_active_spider_before_cancelling_timeout() -> None:
    created_spiders: list[_PausableTimeoutSpider] = []

    class _Spider(_PausableTimeoutSpider):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            created_spiders.append(self)

    config = CrawlConfig(spider_timeout=1)
    orch = Orchestrator(db_pool=MagicMock(), config=config, mode="full")
    orch.task_manager = MagicMock()
    orch.task_manager.start_task = AsyncMock(return_value=99)
    orch.task_manager.finish_task = AsyncMock()

    with patch("gaokao_vault.scheduler.orchestrator.SPIDER_MAP", {"schools": _Spider}):
        stats = asyncio.run(orch.run_single("schools"))

    assert stats["failed"] == 1
    assert created_spiders[0].pause_called_while_active is True
    orch.task_manager.finish_task.assert_awaited_once()
