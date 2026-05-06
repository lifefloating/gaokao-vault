from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

from gaokao_vault.config import CrawlConfig, DatabaseConfig
from gaokao_vault.db.queries.majors import find_major_by_code, find_major_by_source_id
from gaokao_vault.spiders.school_major_spider import SchoolMajorSpider


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


class _FakeMajorLookupConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def fetch(self, _query: str, _value: str):
        return self.rows


class _FakeTaskStatusConnection:
    def __init__(
        self,
        task_rows: dict[str, dict | None],
        schools: list[dict] | None = None,
        *,
        school_count: int | None = None,
        major_count: int | None = None,
    ) -> None:
        self.task_rows = task_rows
        self.schools = schools or []
        self.school_count = school_count if school_count is not None else len(self.schools)
        self.major_count = major_count if major_count is not None else 0
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, _query: str, task_type: str):
        return self.task_rows.get(task_type)

    async def fetch(self, query: str, *args: object):
        self.fetch_calls.append((query, args))
        if "FROM schools ORDER BY id" in query:
            return self.schools
        return []

    async def fetchval(self, query: str, *args: object):
        self.fetchval_calls.append((query, args))
        if "COUNT(*) FROM schools" in query:
            return self.school_count
        if "COUNT(*) FROM majors" in query:
            return self.major_count
        return None


def _make_school_major_spider(config: CrawlConfig | None = None) -> SchoolMajorSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return SchoolMajorSpider(db_config=db_config, crawl_task_id=1, config=config)


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


def test_find_major_by_code_returns_none_when_code_is_ambiguous():
    conn = _FakeMajorLookupConnection([
        {"id": 1, "code": "080901", "name": "计算机科学与技术"},
        {"id": 2, "code": "080901", "name": "计算机科学与技术"},
    ])

    result = asyncio.run(find_major_by_code(cast(Any, conn), "080901"))

    assert result is None


def test_find_major_by_source_id_returns_none_when_source_id_is_ambiguous():
    conn = _FakeMajorLookupConnection([
        {"id": 1, "source_id": "73381091", "code": "020301", "name": "金融学"},
        {"id": 2, "source_id": "73381091", "code": "020301", "name": "金融学"},
    ])

    result = asyncio.run(find_major_by_source_id(cast(Any, conn), "73381091"))

    assert result is None


def test_parse_keeps_existing_code_match_path():
    spider = _make_school_major_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" data-code="080901" href="/zyk/080901">计算机科学与技术</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-1.dhtml",
        {"school_id": 7, "sch_id": 1},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value={"id": 9})),
        patch("gaokao_vault.spiders.school_major_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [{"school_id": 7, "major_id": 9, "school_major_rank": 1, "is_featured_major": True}]


def test_parse_falls_back_to_exact_name_when_code_is_missing():
    spider = _make_school_major_spider()
    spider._allow_name_fallback = True
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" href="/zyk?name=临床医学">临床医学</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-2.dhtml",
        {"school_id": 8, "sch_id": 2},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value=None)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12, "name": "临床医学"}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [{"school_id": 8, "major_id": 12, "school_major_rank": 1, "is_featured_major": True}]


def test_parse_tries_href_code_when_data_code_does_not_match():
    spider = _make_school_major_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" data-code="BADCODE" href="/zyk?code=100201">临床医学</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-4.dhtml",
        {"school_id": 10, "sch_id": 4},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_major_by_code",
            new=AsyncMock(side_effect=[None, {"id": 15}]),
        ),
        patch("gaokao_vault.spiders.school_major_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [{"school_id": 10, "major_id": 15, "school_major_rank": 1, "is_featured_major": True}]


def test_parse_resolves_by_source_id_from_professional_page():
    spider = _make_school_major_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div class="yxk-zyjs-tab">
              <ul class="clearfix">
                <li><a href="/sch/zyk/view.do?schId=73394646&specId=73381091">金融学</a></li>
              </ul>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/listzyjs--schId-35,categoryId-417877,mindex-3.dhtml",
        {"school_id": 11, "sch_id": 35},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value={"id": 21})
        ),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [{"school_id": 11, "major_id": 21, "school_major_rank": 1, "is_featured_major": True}]


def test_parse_uses_bare_path_href_code_when_data_code_is_missing():
    spider = _make_school_major_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" href="/zyk/080901">计算机科学与技术</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-5.dhtml",
        {"school_id": 11, "sch_id": 5},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value={"id": 16})),
        patch("gaokao_vault.spiders.school_major_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [{"school_id": 11, "major_id": 16, "school_major_rank": 1, "is_featured_major": True}]


def test_parse_assigns_school_major_rank_and_flags_top_three_as_featured():
    spider = _make_school_major_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" data-code="080901" href="/zyk/080901">计算机科学与技术</a>
              <a class="major-link" data-code="080902" href="/zyk/080902">软件工程</a>
              <a class="major-link" data-code="080903" href="/zyk/080903">网络工程</a>
              <a class="major-link" data-code="080904" href="/zyk/080904">信息安全</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-7.dhtml",
        {"school_id": 17, "sch_id": 7},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_major_by_code",
            new=AsyncMock(side_effect=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]),
        ),
        patch("gaokao_vault.spiders.school_major_spider.find_majors_by_name", new=AsyncMock(return_value=[])),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert [item["school_major_rank"] for item in items] == [1, 2, 3, 4]
    assert [item["is_featured_major"] for item in items] == [True, True, True, False]


def test_parse_skips_ambiguous_exact_name_matches(caplog):
    spider = _make_school_major_spider()
    spider._allow_name_fallback = True
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" data-code="BADCODE" href="/zyk?code=120201">工商管理</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-3.dhtml",
        {"school_id": 9, "sch_id": 3},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value=None)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 18}, {"id": 19}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == []
    assert "Ambiguous major match" in caplog.text
    assert "data_code=BADCODE" in caplog.text
    assert "href_code=120201" in caplog.text


def test_parse_skips_name_fallback_when_policy_disables_it(caplog):
    spider = _make_school_major_spider()
    spider._allow_name_fallback = False
    response = _make_response(
        """
        <html>
          <body>
            <div class="major-list">
              <a class="major-link" href="/zyk?name=临床医学">临床医学</a>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-6.dhtml",
        {"school_id": 12, "sch_id": 6},
    )

    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_source_id", new=AsyncMock(return_value=None)),
        patch("gaokao_vault.spiders.school_major_spider.find_major_by_code", new=AsyncMock(return_value=None)),
        patch(
            "gaokao_vault.spiders.school_major_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12, "name": "临床医学"}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == []
    assert "Name fallback disabled" in caplog.text


def test_start_requests_skips_when_schools_task_is_not_stable():
    spider = _make_school_major_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "failed", "failed_items": 1, "finished_at": "2026-04-23T00:00:00"},
            "majors": {"status": "success", "failed_items": 0, "finished_at": "2026-04-23T00:00:00"},
        },
        schools=[{"id": 1, "sch_id": 34}],
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests == []
    assert all("FROM schools ORDER BY id" not in query for query, _args in conn.fetch_calls)


def test_start_requests_skips_when_majors_task_is_not_stable():
    spider = _make_school_major_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "success", "failed_items": 0, "finished_at": "2026-04-23T00:00:00"},
            "majors": {"status": "running", "failed_items": 0, "finished_at": None},
        },
        schools=[{"id": 1, "sch_id": 34}],
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests == []
    assert all("FROM schools ORDER BY id" not in query for query, _args in conn.fetch_calls)


def test_start_requests_yields_school_requests_when_upstreams_are_stable():
    spider = _make_school_major_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "success", "failed_items": 0, "finished_at": "2026-04-23T00:00:00"},
            "majors": {"status": "success", "failed_items": 0, "finished_at": "2026-04-23T00:00:00"},
        },
        schools=[{"id": 1, "sch_id": 34}, {"id": 2, "sch_id": 35}],
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert [request.meta["school_id"] for request in requests] == [1, 2]
    assert [request.meta["sch_id"] for request in requests] == [34, 35]


def test_start_requests_uses_existing_upstream_rows_when_latest_school_task_failed():
    spider = _make_school_major_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "failed", "failed_items": 1, "finished_at": "2026-04-23T00:00:00"},
            "majors": {"status": "success", "failed_items": 0, "finished_at": "2026-04-23T00:00:00"},
        },
        schools=[{"id": 1, "sch_id": 34}],
        school_count=2800,
        major_count=1800,
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert len(requests) == 1
    assert requests[0].meta == {"school_id": 1, "sch_id": 34}
    assert [query for query, _args in conn.fetchval_calls] == [
        "SELECT COUNT(*) FROM schools",
        "SELECT COUNT(*) FROM majors",
    ]


def test_start_requests_uses_configured_upstream_row_thresholds():
    spider = _make_school_major_spider(
        CrawlConfig(
            school_major_min_ready_schools=3000,
            school_major_min_ready_majors=2000,
        )
    )
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "failed", "failed_items": 1, "finished_at": "2026-04-23T00:00:00"},
            "majors": {"status": "running", "failed_items": 0, "finished_at": None},
        },
        schools=[{"id": 1, "sch_id": 34}],
        school_count=2800,
        major_count=1800,
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests == []
    assert all("FROM schools ORDER BY id" not in query for query, _args in conn.fetch_calls)
