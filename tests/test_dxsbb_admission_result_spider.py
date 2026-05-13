from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.fetchers import FetcherSession
from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.dxsbb_admission_result_spider import DxsbbAdmissionResultSpider


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
    async def fetchrow(self, query: str, *args):
        if "FROM crawl_tasks" in query:
            return {"status": "success", "failed_items": 0, "finished_at": "2026-05-02T00:00:00"}
        if "FROM schools" in query and args == ("太原师范学院",):
            return {"id": 102, "name": "太原师范学院"}
        if "FROM schools" in query and args == ("长春理工大学",):
            return {"id": 228, "name": "长春理工大学"}
        if "FROM score_segments" in query:
            score = args[3]
            return {"score": score, "cumulative_count": score * 10}
        return None

    async def fetch(self, query: str, *args):
        if "FROM provinces" in query:
            return [{"id": 14, "name": "山西"}, {"id": 7, "name": "吉林"}]
        if "FROM school_majors" in query and args == (102, "英语", None):
            return [{"id": 31}]
        if "FROM school_majors" in query and args == (102, "书法学", None):
            return [{"id": 32}]
        if "FROM school_majors" in query and args == (228, "光电信息科学与工程", None):
            return [{"id": 56}]
        if "FROM majors" in query and args == ("历史学", None):
            return [{"id": 40}]
        return []

    async def fetchval(self, query: str, *args):
        if "official_exists" in query:
            return False
        return None


def _make_spider() -> DxsbbAdmissionResultSpider:
    def configure_test_sessions(_spider, manager) -> None:
        manager.add("http", FetcherSession())

    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    with patch.object(DxsbbAdmissionResultSpider, "configure_sessions", configure_test_sessions):
        return DxsbbAdmissionResultSpider(db_config=db_config, crawl_task_id=1)


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


def test_parse_list_yields_articles_and_next_page() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="listBox">
            <a href="/news/32168.html"><h3>2025太原师范学院录取分数线(含2023-2024历年)</h3></a>
            <a href="/news/other.html"><h3>太原师范学院怎么样</h3></a>
          </div>
          <div class="listNav"><a href="/news/list_458_2.html"><img alt="下一页"></a></div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/list_458.html",
    )

    requests = asyncio.run(_collect(spider.parse_list(response)))

    assert [request.url for request in requests] == [
        "https://www.dxsbb.com/news/32168.html",
        "https://www.dxsbb.com/news/list_458_2.html",
    ]
    assert requests[0].callback == spider.parse_article
    assert requests[1].callback == spider.parse_list


def test_parse_article_persists_major_admission_results_from_score_table() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="position"><a href="/school/太原师范学院.html">太原师范学院</a></div>
          <div id="article">
            <h1>2025太原师范学院录取分数线(含2023-2024历年)</h1>
            <div class="content">
              <table>
                <tr>
                  <td>年份</td><td>省份</td><td>类别</td><td>科类</td><td>专业名称</td>
                  <td>选考要求</td><td>最高分</td><td>最低分</td><td>平均分</td>
                </tr>
                <tr>
                  <td>2025</td><td>山西</td><td>普通类</td><td>理工/物理类</td><td>英语</td>
                  <td>不提科目要求</td><td>533</td><td>484</td><td>498.8</td>
                </tr>
              </table>
            </div>
          </div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/32168.html",
    )
    process_item = AsyncMock(return_value="new")
    resolve_subject_category = AsyncMock(return_value=7)

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch.object(spider, "_resolve_subject_category", new=resolve_subject_category),
        patch.object(spider, "process_item", new=process_item),
    ):
        items = asyncio.run(_collect(spider.parse_article(response)))

    assert items == [
        {
            "school_id": 102,
            "major_id": 31,
            "province_id": 14,
            "year": 2025,
            "subject_category_id": 7,
            "batch": "普通类",
            "batch_code": "regular",
            "batch_category": "普通批",
            "batch_segment": None,
            "min_score": 484,
            "min_rank": 4840,
            "min_rank_source": "score_segments",
            "min_rank_is_derived": True,
            "avg_score": 498,
            "avg_rank": 4980,
            "max_score": 533,
            "max_rank": 5330,
            "admitted_count": None,
            "plan_count": None,
            "school_code_raw": None,
            "school_name_raw": "太原师范学院",
            "major_group_code": None,
            "major_code_raw": None,
            "campus": None,
            "program_type": None,
            "eligibility_requirements": None,
            "physical_exam_or_political_review": None,
            "political_review_requirement": None,
            "service_obligation": None,
            "major_name_raw": "英语",
            "subject_category_raw": "理工/物理类",
            "batch_raw": "普通类",
            "remark": "选考要求: 不提科目要求",
            "source_url": "https://www.dxsbb.com/news/32168.html",
            "data_source": "dxsbb.com",
            "source_updated_at": None,
            "quality_flags": ["missing_admitted_count"],
        }
    ]
    resolve_subject_category.assert_awaited_once_with("物理类")
    process_item.assert_awaited_once()


def test_parse_article_infers_year_from_section_heading_when_table_has_no_year_column() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="position"><a href="/school/太原师范学院.html">太原师范学院</a></div>
          <div id="article">
            <h1>2025太原师范学院录取分数线(含2023-2024历年)</h1>
            <div class="content">
              <h2>二、2024太原师范学院录取分数线</h2>
              <table>
                <tr>
                  <td>专业</td><td>层次</td><td>学制</td><td>科类</td><td>批次</td>
                  <td>省份</td><td>最高分</td><td>最低分</td>
                </tr>
                <tr>
                  <td>书法学</td><td>本科</td><td>四年</td><td>艺术</td><td>艺术本科批</td>
                  <td>山西省</td><td>498.25</td><td>486.75</td>
                </tr>
              </table>
            </div>
          </div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/32168.html",
    )

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=8)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse_article(response)))

    assert len(items) == 1
    assert items[0]["year"] == 2024
    assert items[0]["major_id"] == 32
    assert items[0]["province_id"] == 14
    assert items[0]["batch"] == "艺术本科批"
    assert items[0]["min_score"] == 486
    assert items[0]["max_score"] == 498


def test_parse_article_infers_year_and_province_from_wrapped_table_heading() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="position"><a href="/school/长春理工大学.html">长春理工大学</a></div>
          <div id="article">
            <h1>2025长春理工大学录取分数线\uff08含2023-2024历年\uff09</h1>
            <div class="content">
              <h2>1、2025长春理工大学录取分数线</h2>
              <p style="text-align:center;"><strong>2025年吉林录取分数线</strong></p>
              <div class="tablebox">
                <table cellspacing="0" cellpadding="0">
                  <tr>
                    <td>批次</td><td>科类</td><td>专业\uff08类\uff09名称</td><td>省控线</td>
                    <td>最高分</td><td>最低分</td><td>平均分</td>
                  </tr>
                  <tr>
                    <td>普通本科批</td><td>物理类</td><td>光电信息科学与工程</td><td>345</td>
                    <td>612</td><td>584</td><td>594.5</td>
                  </tr>
                </table>
              </div>
            </div>
          </div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/32401.html",
    )

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse_article(response)))

    assert len(items) == 1
    assert items[0]["school_id"] == 228
    assert items[0]["major_id"] == 56
    assert items[0]["province_id"] == 7
    assert items[0]["year"] == 2025
    assert items[0]["batch"] == "普通本科批"
    assert items[0]["batch_code"] == "regular"
    assert items[0]["batch_category"] == "普通批"
    assert items[0]["subject_category_raw"] == "物理类"
    assert items[0]["min_score"] == 584
    assert items[0]["min_rank"] == 5840
    assert items[0]["min_rank_source"] == "score_segments"
    assert items[0]["min_rank_is_derived"] is True
    assert items[0]["max_score"] == 612
    assert items[0]["max_rank"] == 6120
    assert items[0]["avg_score"] == 594
    assert items[0]["avg_rank"] == 5940


def test_parse_article_accepts_globally_unique_major_when_school_major_mapping_is_missing() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <div class="position"><a href="/school/太原师范学院.html">太原师范学院</a></div>
          <div id="article">
            <h1>2025太原师范学院录取分数线(含2023-2024历年)</h1>
            <div class="content">
              <table>
                <tr><td>年份</td><td>省份</td><td>类别</td><td>科类</td><td>专业名称</td><td>最低分</td></tr>
                <tr><td>2025</td><td>山西</td><td>普通类</td><td>文史/历史类</td><td>历史学</td><td>512</td></tr>
              </table>
            </div>
          </div>
        </body></html>
        """,
        "https://www.dxsbb.com/news/32168.html",
    )

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=9)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse_article(response)))

    assert len(items) == 1
    assert items[0]["major_id"] == 40
    assert items[0]["major_name_raw"] == "历史学"
