from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor
from scrapling.spiders import Request

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.special_spider import (
    CHSI_STRONG_BASE_SCHOOLS,
    SpecialSpider,
    _decode_js_string,
    _extract_registration_dates,
)


def _make_spider() -> SpecialSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return SpecialSpider(db_config=db_config, crawl_task_id=1)


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


_STRONG_BASE_HTML = """
<html>
  <body>
    <div class="article-content">
      <p>报名网址: https://bm.chsi.com.cn/jcxkzs/sch/10001</p>
      <p>报名时间: 2025年4月10日至2025年4月30日.</p>
      <p>招生专业: 数学类,物理学类.</p>
      <p>入围规则: 按高考成绩确定入围名单.</p>
      <p>校测规则: 学校考核包括笔试和面试.</p>
      <p>录取规则: 按综合成绩择优录取.</p>
      <p>综合成绩公式: 综合成绩=高考成绩*85%+校测成绩*15%.</p>
    </div>
  </body>
</html>
"""


def test_decode_js_string_handles_valid_javascript_escapes() -> None:
    value = r"\u56FD\u9632\u79D1\u6280\u5927\u5B66\nA\"B\/C"

    assert _decode_js_string(value) == '国防科技大学\nA"B/C'


def test_decode_js_string_preserves_malformed_or_unknown_escapes() -> None:
    value = r"C:\data\school\x\q\u12GZ"

    assert _decode_js_string(value) == value


def test_parse_detail_extracts_strong_base_structured_fields() -> None:
    spider = _make_spider()
    response = _make_response(
        _STRONG_BASE_HTML,
        "https://gaokao.chsi.com.cn/gkxx/qjjh/test.html",
        {
            "item_data": {
                "enrollment_type": "强基计划",
                "province_code": "11",
                "year": 2025,
                "title": "测试大学2025年强基计划招生简章",
                "source_url": "https://gaokao.chsi.com.cn/gkxx/qjjh/test.html",
            }
        },
    )

    with (
        patch(
            "gaokao_vault.spiders.special_spider.find_school_by_name",
            new=AsyncMock(return_value={"id": 10001}),
        ),
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(AsyncMock()))),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse_detail(response)))

    assert len(items) == 1
    assert items[0]["school_id"] == 10001
    assert items[0]["special_admission_type"] == "strong_foundation"
    assert items[0]["province_code"] == "11"
    assert items[0]["application_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/10001"
    assert items[0]["registration_window"] == {"start": "2025-04-10", "end": "2025-04-30"}
    assert str(items[0]["registration_start"]) == "2025-04-10"
    assert str(items[0]["registration_end"]) == "2025-04-30"
    assert items[0]["eligible_majors"] == ["数学类", "物理学类"]
    assert items[0]["shortlist_rule"] == "按高考成绩确定入围名单"
    assert items[0]["selection_rule"] == "按高考成绩确定入围名单"
    assert items[0]["school_assessment"] == "学校考核包括笔试和面试"
    assert items[0]["school_exam_rule"] == "学校考核包括笔试和面试"
    assert items[0]["composite_score_formula"] == "综合成绩=高考成绩*85%+校测成绩*15%"
    assert items[0]["admission_rule"] == "按综合成绩择优录取"
    assert items[0]["quality_flags"] == []


def test_parse_dxsbb_list_yields_special_article_requests() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div class="listBox">
          <a href="/news/70169.html" target="_blank">
            <div class="b"><h3>强基计划招生程序及管理要求</h3><p class="time">2026-4-7</p></div>
          </a>
          <a href="/news/1978.html" target="_blank">
            <div class="b"><h3>平行志愿录取规则流程</h3><p class="time">2025-5-15</p></div>
          </a>
        </div>
        """,
        "https://www.dxsbb.com/news/list_130.html",
        {"enrollment_type": "强基计划", "special_admission_type": "strong_foundation"},
    )

    results = asyncio.run(_collect(spider.parse_dxsbb_list(response)))

    assert len(results) == 1
    assert isinstance(results[0], Request)
    assert results[0].url == "https://www.dxsbb.com/news/70169.html"
    assert results[0].meta["title"] == "强基计划招生程序及管理要求"
    assert results[0].meta["enrollment_type"] == "强基计划"
    assert results[0].meta["special_admission_type"] == "strong_foundation"


def test_parse_dxsbb_article_persists_special_enrollment_content() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <div id="article">
          <h1>强基计划招生程序及管理要求</h1>
          <div class="update">更新:2026-4-7 10:20:00&nbsp;&nbsp;发布:大学生必备网</div>
          <div class="content">
            <p>报名时间: 2026年4月10日至2026年4月30日.</p>
            <p>招生专业: 数学类,物理学类.</p>
            <p>录取规则: 按综合成绩择优录取.</p>
          </div>
        </div>
        """,
        "https://www.dxsbb.com/news/70169.html",
        {
            "enrollment_type": "强基计划",
            "special_admission_type": "strong_foundation",
            "title": "强基计划招生程序及管理要求",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        items = asyncio.run(_collect(spider.parse_dxsbb_article(response)))

    assert len(items) == 1
    assert items[0]["enrollment_type"] == "强基计划"
    assert items[0]["special_admission_type"] == "strong_foundation"
    assert items[0]["year"] == 2026
    assert items[0]["title"] == "强基计划招生程序及管理要求"
    assert items[0]["source_url"] == "https://www.dxsbb.com/news/70169.html"
    assert items[0]["content_text"] == (
        "报名时间: 2026年4月10日至2026年4月30日.\n招生专业: 数学类,物理学类.\n录取规则: 按综合成绩择优录取."
    )
    assert str(items[0]["publish_date"]) == "2026-04-07"
    assert str(items[0]["registration_start"]) == "2026-04-10"
    assert str(items[0]["registration_end"]) == "2026-04-30"
    assert items[0]["eligible_majors"] == ["数学类", "物理学类"]
    process_item.assert_awaited_once()


def test_parse_chsi_strong_base_school_page_persists_official_charter() -> None:
    spider = _make_spider()
    response = _make_response(
        r"""
        <html>
          <head><title>国防科技大学2026年强基计划报名平台</title></head>
          <body>
            <script>
              var mixin = {
                data: function () {
                  return {
                    jzbt: "\u56FD\u9632\u79D1\u6280\u5927\u5B662026\u5E74\u5F3A\u57FA\u8BA1\u5212\u62DB\u751F\u7B80\u7AE0",
                    time:"2026-04-09 18:00 \u81F3 2026-05-01 00:00",
                    content: "<p>\u62DB\u751F\u4E13\u4E1A: \u6570\u5B66\u4E0E\u5E94\u7528\u6570\u5B66,\u7269\u7406\u5B66.</p><p>\u5F55\u53D6\u89C4\u5219: \u6309\u7EFC\u5408\u6210\u7EE9\u62E9\u4F18\u5F55\u53D6.</p><p>\u7EFC\u5408\u6210\u7EE9\u516C\u5F0F: \u7EFC\u5408\u6210\u7EE9=\u9AD8\u8003\u6210\u7EE9*85%+\u6821\u6D4B\u6210\u7EE9*15%.</p>"
                  }
                }
              }
            </script>
          </body>
        </html>
        """,
        "https://bm.chsi.com.cn/jcxkzs/sch/92002",
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        items = asyncio.run(_collect(spider.parse_chsi_strong_base_school(response)))

    assert len(items) == 2
    charter_item = items[0]
    followup_request = items[1]
    assert charter_item["enrollment_type"] == "强基计划"
    assert charter_item["special_admission_type"] == "strong_foundation"
    assert charter_item["school_code_raw"] == "92002"
    assert charter_item["school_name_raw"] == "国防科技大学"
    assert charter_item["source_section"] == "charter"
    assert charter_item["year"] == 2026
    assert charter_item["title"] == "国防科技大学2026年强基计划招生简章"
    assert charter_item["application_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/92002"
    assert charter_item["source_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/92002"
    assert str(charter_item["registration_start"]) == "2026-04-09"
    assert str(charter_item["registration_end"]) == "2026-05-01"
    assert charter_item["registration_window"] == {"start": "2026-04-09", "end": "2026-05-01"}
    assert charter_item["eligible_majors"] == ["数学与应用数学", "物理学"]
    assert charter_item["composite_score_formula"] == "综合成绩=高考成绩*85%+校测成绩*15%"
    assert charter_item["admission_rule"] == "按综合成绩择优录取"
    assert charter_item["quality_flags"] == []
    assert isinstance(followup_request, Request)
    assert followup_request.url == "https://bm.chsi.com.cn/jcxkzs/sch/ggtzs/92002"
    assert followup_request.meta["school_code_raw"] == "92002"
    assert followup_request.meta["application_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/92002"
    process_item.assert_awaited_once()


def test_parse_chsi_strong_base_school_yields_announcement_request() -> None:
    spider = _make_spider()
    response = _make_response(
        "<html></html>",
        "https://bm.chsi.com.cn/jcxkzs/sch/92002",
    )

    results = asyncio.run(_collect(spider.parse_chsi_strong_base_school(response)))

    assert len(results) == 1
    assert isinstance(results[0], Request)
    assert results[0].url == "https://bm.chsi.com.cn/jcxkzs/sch/ggtzs/92002"
    assert results[0].meta == {
        "school_code_raw": "92002",
        "application_url": "https://bm.chsi.com.cn/jcxkzs/sch/92002",
    }


def test_parse_chsi_strong_base_school_does_not_persist_empty_generated_charter() -> None:
    spider = _make_spider()
    response = _make_response(
        "<html><head><title>国防科技大学2026年强基计划报名平台</title></head><body></body></html>",
        "https://bm.chsi.com.cn/jcxkzs/sch/92002",
        {
            "school_code_raw": "92002",
            "school_name_raw": "国防科技大学",
            "application_url": "https://bm.chsi.com.cn/jcxkzs/sch/92002",
        },
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        results = asyncio.run(_collect(spider.parse_chsi_strong_base_school(response)))

    assert len(results) == 1
    assert isinstance(results[0], Request)
    process_item.assert_not_awaited()


def test_parse_chsi_strong_base_school_preserves_unescaped_chinese_vue_content() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html>
          <head><title>国防科技大学2026年强基计划报名平台</title></head>
          <body>
            <script>
              var mixin = {
                data: function () {
                  return {
                    jzbt: "国防科技大学2026年强基计划招生简章",
                    time:"2026-04-09 18:00 至 2026-05-01 00:00",
                    content: "<p>招生专业: 数学与应用数学,物理学.</p><p>录取规则: 按综合成绩择优录取.</p>"
                  }
                }
              }
            </script>
          </body>
        </html>
        """,
        "https://bm.chsi.com.cn/jcxkzs/sch/92002",
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")):
        items = asyncio.run(_collect(spider.parse_chsi_strong_base_school(response)))

    assert items[0]["title"] == "国防科技大学2026年强基计划招生简章"
    assert items[0]["content_text"] == "招生专业: 数学与应用数学,物理学.\n录取规则: 按综合成绩择优录取."
    assert items[0]["eligible_majors"] == ["数学与应用数学", "物理学"]


def test_parse_chsi_strong_base_announcements_yields_detail_request() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html>
          <body>
            <a href="/jcxkzs/sch/viewggtz/92002/101">国防科技大学2026年强基计划录取标准</a>
            <a href="/jcxkzs/sch/download/yxdm/92002/fjId/9">附件下载</a>
          </body>
        </html>
        """,
        "https://bm.chsi.com.cn/jcxkzs/sch/ggtzs/92002",
        {"school_code_raw": "92002", "application_url": "https://bm.chsi.com.cn/jcxkzs/sch/92002"},
    )

    items = asyncio.run(_collect(spider.parse_chsi_strong_base_announcements(response)))

    assert len(items) == 1
    assert isinstance(items[0], Request)
    assert items[0].url == "https://bm.chsi.com.cn/jcxkzs/sch/viewggtz/92002/101"
    assert items[0].meta["school_code_raw"] == "92002"
    assert items[0].meta["application_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/92002"


def test_parse_chsi_strong_base_announcement_detail_persists_notice_content() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html>
          <body>
            <div id="article">
              <h1>国防科技大学2026年强基计划录取标准</h1>
              <div class="update">更新:2026-7-5 10:00:00&nbsp;&nbsp;发布:国防科技大学</div>
              <div class="content">
                <p>录取规则: 按综合成绩择优录取.</p>
                <p>报名时间: 2026年4月9日至2026年5月1日.</p>
              </div>
            </div>
          </body>
        </html>
        """,
        "https://bm.chsi.com.cn/jcxkzs/sch/viewggtz/92002/101",
        {"school_code_raw": "92002", "application_url": "https://bm.chsi.com.cn/jcxkzs/sch/92002"},
    )

    with patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item:
        items = asyncio.run(_collect(spider.parse_chsi_strong_base_announcement_detail(response)))

    assert len(items) == 1
    assert items[0]["source_section"] == "announcement"
    assert items[0]["school_code_raw"] == "92002"
    assert items[0]["title"] == "国防科技大学2026年强基计划录取标准"
    assert items[0]["source_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/viewggtz/92002/101"
    assert items[0]["application_url"] == "https://bm.chsi.com.cn/jcxkzs/sch/92002"
    assert items[0]["registration_window"] == {"start": "2026-04-09", "end": "2026-05-01"}
    process_item.assert_awaited_once()


def test_chsi_strong_base_fallback_school_list_covers_current_trial_school_count() -> None:
    school_codes = [school_code for school_code, _school_name in CHSI_STRONG_BASE_SCHOOLS]

    assert len(CHSI_STRONG_BASE_SCHOOLS) == 39
    assert len(set(school_codes)) == 39
    assert "92002" in school_codes
    assert "10183" in school_codes


def test_extract_registration_dates_returns_empty_values_for_invalid_dates() -> None:
    assert _extract_registration_dates("报名时间: 2024年13月1日至2024年13月31日") == (None, None)


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
