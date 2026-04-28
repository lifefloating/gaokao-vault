from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.score_segment_spider import ScoreSegmentSpider


class _Acquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _FakeConnection:
    async def fetch(self, query: str, *args: object):
        if "FROM provinces ORDER BY id" in query:
            return [{"id": 7, "name": "吉林", "code": "22"}]
        return []


async def _collect(async_gen) -> list:
    items = []
    async for item in async_gen:
        items.append(item)
    return items


def _make_spider() -> ScoreSegmentSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return ScoreSegmentSpider(db_config=db_config, crawl_task_id=1, mode="incremental")


def test_start_requests_uses_province_code_and_recent_year_window() -> None:
    spider = _make_spider()

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch("gaokao_vault.spiders.score_segment_spider.YEAR_END", 2026),
    ):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert [request.meta["year"] for request in requests] == [2024, 2025, 2026]
    assert all(request.meta["province_id"] == 7 for request in requests)
    assert all(request.meta["province_code"] == "22" for request in requests)
    assert all("provinceId=22" in request.url for request in requests)
