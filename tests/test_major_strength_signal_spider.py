from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.major_strength_signal_spider import MajorStrengthSignalSpider


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


def _make_spider() -> MajorStrengthSignalSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return MajorStrengthSignalSpider(db_config=db_config, crawl_task_id=1)


def _make_response(html: str, url: str, meta: dict | None = None) -> MagicMock:
    adaptor = Adaptor(content=html, url=url)
    response = MagicMock()
    response.status = 200
    response.url = url
    response.css = adaptor.css
    response.request = MagicMock()
    response.request.meta = meta or {}
    response.request.url = url
    return response


async def _collect(async_gen) -> list:
    items = []
    async for item in async_gen:
        items.append(item)
    return items


def test_parse_school_major_page_persists_authoritative_strength_signals() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="major-list">
            <a class="major-link" data-code="080901" href="/zyk/080901">
              计算机科学与技术 国家级一流本科专业建设点
            </a>
            <a class="major-link" data-code="080902" href="/zyk/080902">
              软件工程 省级一流本科专业建设点
            </a>
            <a class="major-link" data-code="080903" href="/zyk/080903">网络工程</a>
          </div>
        </body></html>
        """,
        "https://gaokao.chsi.com.cn/sch/listzyjs--schId-1,categoryId-417877,mindex-3.dhtml",
        {"school_id": 7, "sch_id": 1},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch(
            "gaokao_vault.spiders.major_strength_signal_spider.find_major_by_source_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gaokao_vault.spiders.major_strength_signal_spider.find_major_by_code",
            new=AsyncMock(side_effect=[{"id": 31}, {"id": 32}, {"id": 33}]),
        ),
        patch("gaokao_vault.spiders.major_strength_signal_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert [item["major_id"] for item in items] == [31, 32]
    assert items[0]["signal_type"] == "first_class_major"
    assert items[0]["signal_level"] == "national"
    assert items[0]["strength_score"] == 100
    assert items[1]["signal_level"] == "provincial"
    assert items[1]["strength_score"] == 70
    assert process_item.await_count == 2


def test_on_close_refreshes_strength_rollup_for_current_task() -> None:
    spider = _make_spider()
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch(
            "gaokao_vault.spiders.major_strength_signal_spider.refresh_school_major_strength_rollup", new=AsyncMock()
        ) as refresh_rollup,
        patch("gaokao_vault.db.queries.crawl_meta.update_task_stats", new=AsyncMock()),
    ):
        asyncio.run(spider.on_close())

    refresh_rollup.assert_awaited_once()
    assert refresh_rollup.await_args is not None
    assert refresh_rollup.await_args.kwargs == {"crawl_task_id": 1}
