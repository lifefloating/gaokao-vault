from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor
from scrapling.spiders import Request

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.timeline_spider import TimelineSpider


def _make_spider() -> TimelineSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return TimelineSpider(db_config=db_config, crawl_task_id=1)


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


def test_parse_dxsbb_list_yields_province_timeline_article_requests() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div class="listBox">
          <a href="/news/117345.html" target="_blank">
            <div class="b"><h3>2025安徽高考志愿填报时间和截止时间</h3><p class="time">2025-6-12</p></div>
          </a>
          <a href="/news/57188.html" target="_blank">
            <div class="b"><h3>2025高考志愿填报指南手册</h3><p class="time">2025-5-15</p></div>
          </a>
        </div>
        """,
        "https://www.dxsbb.com/news/list_916.html",
    )

    results = asyncio.run(_collect(spider.parse_dxsbb_list(response)))

    assert len(results) == 1
    assert isinstance(results[0], Request)
    assert results[0].url == "https://www.dxsbb.com/news/117345.html"
    assert results[0].meta["province_id"] == 12
    assert results[0].meta["province_name"] == "安徽"
    assert results[0].meta["year"] == 2025


def test_parse_dxsbb_article_extracts_timeline_table_rows() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div id="article">
          <h1>2025安徽高考志愿填报时间和截止时间</h1>
          <div class="content">
            <table>
              <tr><td colspan="2">志愿填报时间表</td></tr>
              <tr><td>批次</td><td>时段</td></tr>
              <tr><td>普通本科提前批</td><td>6月29日8:00至7月1日17:00</td></tr>
              <tr><td>普通本科批</td><td>7月4日8:00至7月7日17:00</td></tr>
              <tr><td colspan="2">征集志愿填报时间表</td></tr>
              <tr><td>普通本科提前批</td><td>7月15日10:00至16:00</td></tr>
            </table>
          </div>
        </div>
        """,
        "https://www.dxsbb.com/news/117345.html",
        {
            "province_id": 12,
            "province_name": "安徽",
            "year": 2025,
            "title": "2025安徽高考志愿填报时间和截止时间",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    assert len(items) == 3
    assert items[0]["province_id"] == 12
    assert items[0]["year"] == 2025
    assert items[0]["batch"] == "普通本科提前批"
    assert str(items[0]["start_time"]) == "2025-06-29 08:00:00"
    assert str(items[0]["end_time"]) == "2025-07-01 17:00:00"
    assert items[2]["batch"] == "普通本科提前批(征集志愿)"
    assert str(items[2]["start_time"]) == "2025-07-15 10:00:00"
    assert str(items[2]["end_time"]) == "2025-07-15 16:00:00"
    assert process_item.await_count == 3


def test_parse_dxsbb_article_keeps_collection_marker_scoped_to_each_table() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div id="article">
          <h1>2025安徽高考志愿填报时间和截止时间</h1>
          <div class="content">
            <table>
              <tr><td colspan="2">征集志愿填报时间表</td></tr>
              <tr><td>批次</td><td>时段</td></tr>
              <tr><td>普通本科提前批</td><td>7月15日10:00至16:00</td></tr>
            </table>
            <table>
              <tr><td>批次</td><td>时段</td></tr>
              <tr><td>普通本科批</td><td>7月4日8:00至7月7日17:00</td></tr>
            </table>
          </div>
        </div>
        """,
        "https://www.dxsbb.com/news/117345.html",
        {
            "province_id": 12,
            "province_name": "安徽",
            "year": 2025,
            "title": "2025安徽高考志愿填报时间和截止时间",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")):
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    assert [item["batch"] for item in items] == ["普通本科提前批(征集志愿)", "普通本科批"]


def test_parse_dxsbb_article_extracts_historical_text_sections() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div id="article">
          <h1>2025广西高考志愿填报时间和截止时间(含2023-2024年)</h1>
          <div class="content">
            <p>2025广西高考志愿填报时间:其中本科提前批、高职高专提前批志愿填报时间:2025年6月25日15:00至29日10:00。</p>
            <h2>1、2025广西高考志愿填报时间</h2>
            <p><strong>本科提前批、高职高专提前批志愿填报时间:2025年6月25日15:00至29日10:00。其他批次志愿填报时间:2025年6月29日15:00至7月3日10:00。</strong></p>
            <h2>2、2024广西高考志愿填报时间</h2>
            <p><strong>本科提前批、高职高专提前批志愿填报时间:2024年6月25日15:00至29日10:00。其他批次志愿填报时间:2024年6月29日15:00至7月3日10:00。</strong></p>
          </div>
        </div>
        """,
        "https://www.dxsbb.com/news/117331.html",
        {
            "province_id": 20,
            "province_name": "广西",
            "year": 2025,
            "title": "2025广西高考志愿填报时间和截止时间(含2023-2024年)",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    assert [(item["year"], item["batch"]) for item in items] == [
        (2025, "本科提前批、高职高专提前批"),
        (2025, "其他批次"),
        (2024, "本科提前批、高职高专提前批"),
        (2024, "其他批次"),
    ]
    assert str(items[0]["start_time"]) == "2025-06-25 15:00:00"
    assert str(items[0]["end_time"]) == "2025-06-29 10:00:00"
    assert str(items[3]["start_time"]) == "2024-06-29 15:00:00"
    assert str(items[3]["end_time"]) == "2024-07-03 10:00:00"
    assert process_item.await_count == 4


def test_parse_dxsbb_article_recognizes_year_sections_without_gaokao_keyword() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div id="article">
          <h1>2025广西志愿填报时间和截止时间(含2024年)</h1>
          <div class="content">
            <h2>2025广西志愿填报时间</h2>
            <p>本科提前批志愿填报时间:2025年6月25日15:00至29日10:00。</p>
            <h2>2024广西志愿填报时间</h2>
            <p>本科提前批志愿填报时间:2024年6月25日15:00至29日10:00。</p>
          </div>
        </div>
        """,
        "https://www.dxsbb.com/news/117331.html",
        {
            "province_id": 20,
            "province_name": "广西",
            "year": 2025,
            "title": "2025广西志愿填报时间和截止时间(含2024年)",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")):
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    assert [(item["year"], item["batch"]) for item in items] == [
        (2025, "本科提前批"),
        (2024, "本科提前批"),
    ]
