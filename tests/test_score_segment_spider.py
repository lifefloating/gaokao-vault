from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.score_segment_spider import (
    DXSBB_SEGMENT_INDEX_URL,
    ScoreSegmentSpider,
    _segment_tables,
)


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
        patch("gaokao_vault.spiders.score_segment_spider._latest_eol_index_year", return_value=2025),
    ):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert [request.url for request in requests] == [
        "https://www.eol.cn/e_html/gk/gkfsd/",
        "https://www.eol.cn/e_html/gk/gkfsd/2024.shtml",
        DXSBB_SEGMENT_INDEX_URL,
    ]
    assert requests[0].callback == spider.parse_index
    assert requests[2].callback == spider.parse_dxsbb_index
    assert requests[0].meta["years"] == [2024, 2025, 2026]
    assert requests[0].meta["provinces"] == [{"id": 7, "name": "吉林", "code": "22"}]
    assert requests[2].meta["years"] == [2024, 2025, 2026]


def _make_response(html: str, url: str, meta: dict | None = None):
    adaptor = Adaptor(content=html, url=url)
    response = AsyncMock()
    response.status = 200
    response.url = url
    response.css = adaptor.css
    response.request = AsyncMock()
    response.request.meta = meta or {}
    response.request.url = url
    return response


def test_parse_index_yields_eol_article_requests_for_matching_province_and_year() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div class="chengshi">
          <div class="chengshi-head"><span>吉林</span></div>
          <table>
            <tr class="tr-head"><td>
              <a href="https://www.eol.cn/e_html/gk/gkfsd/2024.shtml"><font>2024年</font></a>
            </td></tr>
            <tr class="tr-cont"><td>
              <a href="https://gaokao.eol.cn/ji_lin/dongtai/202506/t20250625_2677007.shtml" class="news">
                吉林2025年高考历史类考生成绩分段表
              </a>
            </td></tr>
            <tr class="tr-cont"><td>
              <a href="https://gaokao.eol.cn/ji_lin/dongtai/202506/t20250625_2677006.shtml" class="news">
                吉林2025年高考物理类考生成绩分段表
              </a>
            </td></tr>
          </table>
        </div>
        """,
        "https://www.eol.cn/e_html/gk/gkfsd/",
        {"provinces": [{"id": 7, "name": "吉林", "code": "22"}], "years": [2025]},
    )

    requests = asyncio.run(_collect(spider.parse_index(response)))

    assert [request.meta["subject_hint"] for request in requests] == ["历史类", "物理类"]
    assert [request.meta["province_id"] for request in requests] == [7, 7]
    assert [request.meta["year"] for request in requests] == [2025, 2025]
    assert all(request.callback == spider.parse for request in requests)


def test_parse_dxsbb_index_yields_allowed_segment_article_requests() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <h2><a href="/news/list_538.html">吉林</a><a href="/news/list_538.html">更多</a></h2>
          <ul>
            <li><a href="/news/117704.html">2025吉林高考一分一段表(物理类+历史类)</a></li>
            <li><a href="/news/148821.html">2025吉林高考一分一段表(物理类)</a></li>
            <li><a href="/news/148820.html">2023吉林高考一分一段表(理科)</a></li>
            <li><a href="/news/other.html">2025吉林高考分数线</a></li>
          </ul>
        </body></html>
        """,
        DXSBB_SEGMENT_INDEX_URL,
        {"provinces": [{"id": 7, "name": "吉林", "code": "22"}], "years": [2024, 2025]},
    )

    requests = asyncio.run(_collect(spider.parse_dxsbb_index(response)))

    assert [request.url for request in requests] == [
        "https://www.dxsbb.com/news/list_538.html",
        "https://www.dxsbb.com/news/117704.html",
        "https://www.dxsbb.com/news/148821.html",
    ]
    assert requests[0].callback == spider.parse_dxsbb_index
    assert requests[1].callback == spider.parse_dxsbb_article
    assert requests[1].meta == {
        "province_id": 7,
        "province_name": "吉林",
        "province_code": "22",
        "year": 2025,
        "subject_hint": "物理类",
        "data_source": "dxsbb.com",
        "title": "2025吉林高考一分一段表(物理类+历史类)",
    }


def test_segment_tables_prefers_trs_editor_tables_without_duplicate() -> None:
    response = _make_response(
        """
        <html>
          <body>
            <div class="TRS_Editor">
              <table id="segment"><tr><td>分数</td><td>人数</td><td>累计人数</td></tr></table>
            </div>
            <table id="layout"><tr><td>栏目</td></tr></table>
          </body>
        </html>
        """,
        "https://gaokao.eol.cn/test.shtml",
    )

    tables = list(_segment_tables(response))

    assert len(tables) == 1
    assert tables[0].attrib["id"] == "segment"


class _FakeSink:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.total_flushed = 0

    async def add(self, item: dict) -> None:
        self.items.append(item)
        self.total_flushed += 1


def test_parse_eol_score_segment_article_table() -> None:
    spider = _make_spider()
    sink = _FakeSink()
    spider._sink = cast(Any, sink)
    response = _make_response(
        """
        <html>
          <head><title>吉林2025年高考历史类考生成绩分段表</title></head>
          <body>
            <div class="title">吉林2025年高考历史类考生成绩分段表</div>
            <div class="TRS_Editor">
              <table>
                <tr><td>分数</td><td>人数</td><td>累计人数</td></tr>
                <tr><td>673-750</td><td>11</td><td>11</td></tr>
                <tr><td>672</td><td>1</td><td>12</td></tr>
              </table>
            </div>
          </body>
        </html>
        """,
        "https://gaokao.eol.cn/ji_lin/dongtai/202506/t20250625_2677007.shtml",
        {"province_id": 7, "year": 2025, "subject_hint": "历史类"},
    )

    with patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)):
        items = asyncio.run(_collect(spider.parse(response)))

    assert [(item["score"], item["segment_count"], item["cumulative_count"]) for item in items] == [
        (673, 11, 11),
        (672, 1, 12),
    ]
    assert all(item["subject_category_id"] == 3 for item in items)
    assert len(sink.items) == 2
    assert spider._stats["updated"] == 2


def test_parse_dxsbb_article_uses_vision_for_image_segment_table() -> None:
    spider = _make_spider()
    sink = _FakeSink()
    spider._sink = cast(Any, sink)
    response = _make_response(
        """
        <html><body>
          <div id="article">
            <h1>2025吉林高考一分一段表(物理类)</h1>
            <div class="content">
              <p>以下是吉林2025年高考物理类一分一段表。</p>
              <img src="/uploads/allimg/250625/1-250625160602.jpg" alt="2025吉林高考一分一段表(物理类)">
            </div>
          </div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/148821.html",
        {
            "province_id": 7,
            "province_name": "吉林",
            "province_code": "22",
            "year": 2025,
            "subject_hint": "物理类",
            "data_source": "dxsbb.com",
        },
    )

    with (
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch.object(
            spider,
            "_analyze_dxsbb_segment_image",
            new=AsyncMock(
                return_value=[
                    {"category": "物理类", "score": 600, "segment_count": 120, "cumulative_count": 5529},
                    {"category": "物理类", "score": 599, "segment_count": 130, "cumulative_count": 5659},
                ]
            ),
        ) as analyze_image,
    ):
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    analyze_image.assert_awaited_once_with(
        "https://www.dxsbb.com/uploads/allimg/250625/1-250625160602.jpg",
        province_name="吉林",
        year=2025,
        subject_hint="物理类",
    )
    assert [(item["score"], item["segment_count"], item["cumulative_count"]) for item in items] == [
        (600, 120, 5529),
        (599, 130, 5659),
    ]
    assert all(item["subject_category_id"] == 3 for item in items)
    assert len(sink.items) == 2
