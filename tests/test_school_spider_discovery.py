from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.school_spider import SchoolSpider


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


def _make_school_spider() -> SchoolSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return SchoolSpider(db_config=db_config, crawl_task_id=1)


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


_SEARCH_HTML = """
<html>
  <body>
    <div class="search-filter">
      <a href="/sch/search--ss-on,schProvince-北京,searchType-1,start-0.dhtml">北京</a>
      <a href="/sch/search--ss-on,schProvince-河北,searchType-1,start-0.dhtml">河北</a>
    </div>
  </body>
</html>
"""


_LIST_HTML = """
<html>
  <body>
    <div class="schools-list">
      <a href="/sch/schoolInfoMain--schId-10.dhtml">北京大学</a>
      <a href="/sch/schoolInfoMain--schId-11.dhtml">清华大学</a>
      <a href="/sch/search--ss-on,schProvince-北京,searchType-1,start-20.dhtml">下一页</a>
    </div>
  </body>
</html>
"""


_DETAIL_HTML = """
<html>
  <body>
    <div class="content-header">测试大学</div>
    <div class="content-introduction"><span>教育部</span></div>
  </body>
</html>
"""


def test_start_requests_emits_only_warmup_and_search_entry():
    spider = _make_school_spider()

    with patch("gaokao_vault.spiders.school_spider.MAX_SCH_ID", 2):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert len(requests) == 4
    assert requests[0].callback.__name__ == "parse_warmup"
    assert requests[1].callback.__name__ == "parse_search_entry"
    assert requests[0].url == (
        "https://gaokao.chsi.com.cn/sch/search--ss-on,searchType-1,dataType-2,"
        "schName-,schProvince-,schAddress-,schType-,xlcc-,yxls-,"
        "dual-,naession-,f211-,f985-,autonomy-,central-,start-0.dhtml"
    )
    assert requests[1].url == "https://gaokao.chsi.com.cn/sch/search--ss-on,option-qg,searchType-1,start-0.dhtml"
    assert [request.meta["sch_id"] for request in requests[2:]] == [1, 2]
    assert all(request.callback.__name__ == "parse" for request in requests[2:])


def test_parse_search_entry_yields_province_requests():
    spider = _make_school_spider()
    response = _make_response(
        _SEARCH_HTML,
        "https://gaokao.chsi.com.cn/sch/search--ss-on,option-qg,searchType-1,start-0.dhtml",
    )

    with patch.object(
        spider,
        "_load_province_map",
        new=AsyncMock(return_value={"北京": 1, "河北": 3}),
    ):
        requests = asyncio.run(_collect(spider.parse_search_entry(response)))

    assert [request.meta["candidate_province_id"] for request in requests] == [1, 3]
    assert all(request.callback.__name__ == "parse_school_list" for request in requests)


def test_parse_search_entry_keeps_unmappable_province_links_when_resolution_fails():
    spider = _make_school_spider()
    response = _make_response(
        """
        <html>
          <body>
            <a href="/sch/search--ss-on,schProvince-未知,searchType-1,start-0.dhtml">未知地区</a>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/search--ss-on,option-qg,searchType-1,start-0.dhtml",
    )

    with patch.object(spider, "_resolve_province_id", new=AsyncMock(side_effect=RuntimeError("boom"))):
        requests = asyncio.run(_collect(spider.parse_search_entry(response)))

    assert len(requests) == 1
    assert requests[0].meta["candidate_province_id"] is None
    assert requests[0].callback.__name__ == "parse_school_list"


def test_parse_school_list_yields_detail_requests_and_next_page():
    spider = _make_school_spider()
    response = _make_response(
        _LIST_HTML,
        "https://gaokao.chsi.com.cn/sch/search--ss-on,schProvince-北京,searchType-1,start-0.dhtml",
        {"candidate_province_id": 1, "province_name": "北京"},
    )

    requests = asyncio.run(_collect(spider.parse_school_list(response)))

    detail_requests = [request for request in requests if "schoolInfoMain--schId-" in request.url]
    pagination_requests = [request for request in requests if "start-20" in request.url]

    assert {request.meta["sch_id"] for request in detail_requests} == {10, 11}
    assert all(request.meta["candidate_province_id"] == 1 for request in detail_requests)
    assert len(pagination_requests) == 1
    assert pagination_requests[0].callback.__name__ == "parse_school_list"


def test_parse_uses_candidate_province_when_detail_page_does_not_resolve_one():
    spider = _make_school_spider()
    response = _make_response(
        _DETAIL_HTML,
        "https://gaokao.chsi.com.cn/sch/schoolInfoMain--schId-12.dhtml",
        {"sch_id": 12, "candidate_province_id": 3},
    )

    with (
        patch.object(spider, "_resolve_province_id", new=AsyncMock(return_value=None)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["province_id"] == 3


def test_parse_keeps_candidate_province_when_detail_resolution_raises():
    spider = _make_school_spider()
    response = _make_response(
        _DETAIL_HTML,
        "https://gaokao.chsi.com.cn/sch/schoolInfoMain--schId-13.dhtml",
        {"sch_id": 13, "candidate_province_id": 5},
    )

    with (
        patch.object(spider, "_resolve_province_id", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["province_id"] == 5


def test_parse_preserves_existing_province_when_current_item_has_none():
    spider = _make_school_spider()
    response = _make_response(
        _DETAIL_HTML,
        "https://gaokao.chsi.com.cn/sch/schoolInfoMain--schId-14.dhtml",
        {"sch_id": 14, "candidate_province_id": None},
    )
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1, "sch_id": 14, "name": "测试大学", "province_id": 7})
    fake_pool = _FakePool(conn)

    with (
        patch.object(spider, "_resolve_province_id", new=AsyncMock(return_value=None)),
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["province_id"] == 7


def test_schedule_school_detail_allows_one_candidate_refresh_after_bruteforce():
    spider = _make_school_spider()

    first = spider._schedule_school_detail(12, None)
    second = spider._schedule_school_detail(12, 3)
    third = spider._schedule_school_detail(12, 4)

    assert first is not None
    assert first.meta["candidate_province_id"] is None
    assert second is not None
    assert second.meta["candidate_province_id"] == 3
    assert third is None
