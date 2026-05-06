from __future__ import annotations

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from scrapling.fetchers import FetcherSession
from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.interpretation_spider import InterpretationSpider


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
    async def fetchrow(self, query: str, *_args):
        if "FROM majors" in query and _args == ("计算机科学与技术",):
            return {"id": 31}
        return None


async def _collect(async_gen) -> list:
    items = []
    async for item in async_gen:
        items.append(item)
    return items


def _make_spider() -> InterpretationSpider:
    def configure_test_sessions(_spider, manager) -> None:
        manager.add("http", FetcherSession())

    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    with patch.object(InterpretationSpider, "configure_sessions", configure_test_sessions):
        return InterpretationSpider(db_config=db_config, crawl_task_id=1)


def _make_response(html: str, url: str, meta: dict | None = None) -> MagicMock:
    adaptor = Adaptor(content=html, url=url)
    response = MagicMock()
    response.status = 200
    response.url = url
    response.css = adaptor.css
    response.request = MagicMock()
    response.request.meta = meta or {}
    response.request.url = url
    response.urljoin = adaptor.urljoin
    return response


def test_start_requests_uses_current_major_interpretation_entrypoints() -> None:
    spider = _make_spider()

    requests = asyncio.run(_collect(spider.start_requests()))

    assert [request.url for request in requests] == [
        "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/listPage",
        "https://gaokao.chsi.com.cn/gkxx/zybk/zt",
    ]
    assert all(request.callback == spider.parse for request in requests)


def test_parse_current_list_page_yields_detail_requests_and_next_page() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="zyjd-list">
            <a href="/zyk/zybk/zyjd/viewPage/123">计算机科学与技术专业解读</a>
            <span class="major">计算机科学与技术</span>
            <span class="date">2026-05-06</span>
          </div>
        </body></html>
        """,
        "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/listPage",
        {"page": 1, "entrypoint": "zyjd"},
    )

    requests = asyncio.run(_collect(spider.parse(response)))

    assert [request.url for request in requests] == [
        "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/viewPage/123",
        "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/listPage?page=2",
    ]
    assert requests[0].callback == spider.parse_detail
    assert requests[0].meta["title"] == "计算机科学与技术专业解读"
    assert requests[0].meta["major_name"] == "计算机科学与技术"
    assert requests[0].meta["publish_date"] == "2026-05-06"
    assert requests[1].callback == spider.parse
    assert requests[1].meta == {"page": 2, "entrypoint": "zyjd"}


def test_parse_static_topic_page_yields_legacy_article_details_without_pagination() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <ul class="news-list">
            <li><a href="/gkxx/zybk/zt/201612/20161208/1572763875.html">大气科学专业解读</a></li>
          </ul>
        </body></html>
        """,
        "https://gaokao.chsi.com.cn/gkxx/zybk/zt",
        {"entrypoint": "legacy_topic"},
    )

    requests = asyncio.run(_collect(spider.parse(response)))

    assert len(requests) == 1
    assert requests[0].url == "https://gaokao.chsi.com.cn/gkxx/zybk/zt/201612/20161208/1572763875.html"
    assert requests[0].callback == spider.parse_detail
    assert requests[0].meta["title"] == "大气科学专业解读"


def test_parse_detail_persists_vue_and_static_article_content() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <h1>计算机科学与技术专业解读</h1>
          <div class="content">
            <p>专业名称:计算机科学与技术</p>
            <p>培养目标和就业方向。</p>
          </div>
        </body></html>
        """,
        "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/viewPage/123",
        {
            "title": "计算机科学与技术专业解读",
            "major_name": "计算机科学与技术",
            "publish_date": "2026-05-06",
            "source_url": "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/viewPage/123",
        },
    )
    process_item = AsyncMock(return_value="new")

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch.object(spider, "process_item", new=process_item),
    ):
        items = asyncio.run(_collect(spider.parse_detail(response)))

    assert items == [
        {
            "major_id": 31,
            "title": "计算机科学与技术专业解读",
            "content": "专业名称:计算机科学与技术 培养目标和就业方向。",
            "author": None,
            "publish_date": ANY,
            "source_url": "https://gaokao.chsi.com.cn/zyk/zybk/zyjd/viewPage/123",
        }
    ]
    process_item.assert_awaited_once()
