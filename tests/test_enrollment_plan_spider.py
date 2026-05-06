from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

import gaokao_vault.spiders.enrollment_plan_spider as enrollment_plan_spider
from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.enrollment_plan_spider import EnrollmentPlanSpider


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


class _FakeStartConnection:
    async def fetch(self, query: str, *args: object):
        if "FROM schools ORDER BY id" in query:
            return [{"id": 1, "sch_id": 34, "name": "苏州大学"}]
        if "FROM provinces ORDER BY id" in query:
            return [{"id": 7, "name": "吉林", "code": "22"}]
        return []


def _make_spider() -> EnrollmentPlanSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return EnrollmentPlanSpider(db_config=db_config, crawl_task_id=1)


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


def _make_json_response(payload: dict, url: str, meta: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.url = url
    response.text = json.dumps(payload, ensure_ascii=False)
    response.body = response.text.encode()
    response.request = MagicMock()
    response.request.meta = meta or {}
    response.request.url = url
    return response


async def _collect(async_gen) -> list:
    items = []
    async for item in async_gen:
        items.append(item)
    return items


_PLAN_HTML = """
<html>
  <body>
    <table class="plan-table">
      <tr>
        <th>专业名称</th>
        <th>科类</th>
        <th>批次</th>
        <th>计划数</th>
        <th>学制</th>
        <th>学费</th>
        <th>备注</th>
      </tr>
      <tr>
        <td>计算机科学与技术</td>
        <td>物理类</td>
        <td>本科批</td>
        <td>5</td>
        <td>四年</td>
        <td>5800</td>
        <td>无</td>
      </tr>
    </table>
  </body>
</html>
"""

_ENRICHED_PLAN_HTML = """
<html>
  <body>
    <table class="plan-table">
      <tr>
        <th>院校专业组</th>
        <th>专业代码</th>
        <th>专业名称</th>
        <th>科类</th>
        <th>批次</th>
        <th>计划数</th>
        <th>选科要求</th>
        <th>校区</th>
        <th>办学地点</th>
        <th>学制</th>
        <th>学费</th>
        <th>备注</th>
      </tr>
      <tr>
        <td>01</td>
        <td>080901</td>
        <td>计算机科学与技术</td>
        <td>物理类</td>
        <td>本科提前批A段</td>
        <td>5</td>
        <td>物理+化学</td>
        <td>主校区</td>
        <td>长春市</td>
        <td>四年</td>
        <td>5800</td>
        <td>公费师范生,须通过政审,毕业后服务期6年,不招色盲,英语单科不低于110分,服从专业调剂</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_parse_enrollment_plan_resolves_major_id_and_subject_category() -> None:
    spider = _make_spider()
    response = _make_response(
        _PLAN_HTML,
        "https://gaokao.chsi.com.cn/test",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch(
            "gaokao_vault.spiders.enrollment_plan_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["major_id"] == 12
    assert items[0]["subject_category_id"] == 3
    assert items[0]["batch"] == "本科批"
    assert items[0]["plan_count"] == 5


def test_parse_enrollment_plan_preserves_rule_fields_and_quality_flags() -> None:
    spider = _make_spider()
    response = _make_response(
        _ENRICHED_PLAN_HTML,
        "https://gaokao.chsi.com.cn/test-plan",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch(
            "gaokao_vault.spiders.enrollment_plan_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["major_group_code"] == "01"
    assert items[0]["major_code_raw"] == "080901"
    assert items[0]["selection_requirement"] == "物理+化学"
    assert items[0]["campus"] == "主校区"
    assert items[0]["education_location"] == "长春市"
    assert items[0]["physical_exam_limit"] == "不招色盲"
    assert items[0]["single_subject_limit"] == "英语单科不低于110分"
    assert items[0]["adjustment_rule"] == "服从专业调剂"
    assert items[0]["batch_code"] == "early"
    assert items[0]["batch_category"] == "提前批"
    assert items[0]["batch_segment"] == "A段"
    assert items[0]["program_type"] == "公费师范"
    assert items[0]["eligibility_requirements"] is None
    assert items[0]["physical_exam_or_political_review"] == "不招色盲;须通过政审"
    assert items[0]["political_review_requirement"] == "须通过政审"
    assert items[0]["service_obligation"] == "毕业后服务期6年"
    assert items[0]["data_source"] == "gaokao.chsi.com.cn"
    assert items[0]["source_url"] == "https://gaokao.chsi.com.cn/test-plan"
    assert items[0]["quality_flags"] == []
    process_item.assert_awaited_once()
    await_args = process_item.await_args
    assert await_args is not None
    persisted_item = await_args.args[0]
    assert persisted_item["major_group_code"] == "01"


def test_parse_enrollment_plan_accepts_generic_table_with_matching_headers() -> None:
    spider = _make_spider()
    response = _make_response(
        _PLAN_HTML.replace('class="plan-table"', ""),
        "https://gaokao.chsi.com.cn/generic-plan",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch(
            "gaokao_vault.spiders.enrollment_plan_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["major_name"] == "计算机科学与技术"
    assert items[0]["source_url"] == "https://gaokao.chsi.com.cn/generic-plan"


def test_parse_enrollment_plan_ignores_generic_layout_tables_without_matching_headers() -> None:
    spider = _make_spider()
    html = f"""
    <html>
      <body>
        <table>
          <tr><th>栏目</th><th>内容</th><th>操作</th><th>数量</th></tr>
          <tr><td>计算机科学与技术</td><td>物理类</td><td>本科批</td><td>5</td></tr>
        </table>
        {_PLAN_HTML.replace('class="plan-table"', "")}
      </body>
    </html>
    """
    response = _make_response(
        html,
        "https://gaokao.chsi.com.cn/generic-plan-with-layout",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch(
            "gaokao_vault.spiders.enrollment_plan_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 12}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["major_name"] == "计算机科学与技术"
    assert items[0]["plan_count"] == 5


def test_start_requests_bootstraps_gaokao_school_name_index() -> None:
    spider = _make_spider()
    spider.mode = "incremental"

    get_pool = AsyncMock(return_value=_FakePool(_FakeStartConnection()))
    with patch.object(spider, "_get_pool", new=get_pool):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests
    assert get_pool.await_count == 1
    assert requests[0].url == "https://static-data.gaokao.cn/www/2.0/school/name.json"
    assert requests[0].callback == spider.parse_school_name_index
    assert requests[0].meta["schools"] == [{"id": 1, "sch_id": 34, "name": "苏州大学"}]
    assert requests[0].meta["provinces"] == [{"id": 7, "name": "吉林", "code": "22"}]


def test_parse_school_name_index_yields_per_school_plan_dictionaries() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {
            "code": "0000",
            "data": [
                {"school_id": "118", "name": "苏州大学"},
                {"school_id": "999", "name": "不存在大学"},
            ],
        },
        "https://static-data.gaokao.cn/www/2.0/school/name.json",
        {
            "schools": [{"id": 1, "sch_id": 34, "name": "苏州大学"}],
            "provinces": [{"id": 7, "name": "江苏", "code": "32"}],
            "years": [2025],
        },
    )

    requests = asyncio.run(_collect(spider.parse_school_name_index(response)))

    assert len(requests) == 1
    assert requests[0].url == "https://static-data.gaokao.cn/www/2.0/yk/school/118/dic/specialplan.json"
    assert requests[0].callback == spider.parse_plan_dictionary
    assert requests[0].meta == {
        "school_id": 1,
        "school_name": "苏州大学",
        "gaokao_school_id": "118",
        "provinces": [{"id": 7, "name": "江苏", "code": "32"}],
        "years": [2025],
    }


def test_select_plan_years_uses_previous_three_years_before_december() -> None:
    assert enrollment_plan_spider._select_plan_years("incremental", datetime(2026, 5, 5)) == [2025, 2024, 2023]


def test_select_plan_years_in_december_includes_current_year() -> None:
    assert enrollment_plan_spider._select_plan_years("incremental", datetime(2026, 12, 5)) == [2026, 2025, 2024]


def test_select_plan_years_keeps_full_mode_historical_window() -> None:
    assert enrollment_plan_spider._select_plan_years("full", datetime(2026, 12, 5)) == [
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
        2026,
    ]


def test_parse_plan_dictionary_yields_requested_years_even_when_dictionary_is_incomplete() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {"code": "0000", "data": {"year": {"32": [2025, 2024], "11": [2024]}}},
        "https://static-data.gaokao.cn/www/2.0/yk/school/118/dic/specialplan.json",
        {
            "school_id": 1,
            "school_name": "苏州大学",
            "gaokao_school_id": "118",
            "provinces": [{"id": 7, "name": "江苏", "code": "32"}, {"id": 8, "name": "北京", "code": "11"}],
            "years": [2023, 2024, 2025],
        },
    )

    requests = asyncio.run(_collect(spider.parse_plan_dictionary(response)))

    assert [request.url for request in requests] == [
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2023/32.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2024/32.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2025/32.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2023/11.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2024/11.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2025/11.json",
    ]
    assert requests[0].meta["province_code"] == "32"
    assert requests[0].meta["year"] == 2023
    assert requests[1].meta["province_code"] == "32"
    assert requests[1].meta["year"] == 2024
    assert requests[2].meta["province_code"] == "32"
    assert requests[2].meta["year"] == 2025
    assert requests[3].meta["province_code"] == "11"
    assert requests[3].meta["year"] == 2023
    assert requests[4].meta["province_code"] == "11"
    assert requests[4].meta["year"] == 2024
    assert requests[5].meta["province_code"] == "11"
    assert requests[5].meta["year"] == 2025


def test_parse_plan_dictionary_normalizes_dirty_requested_years() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {"code": "0000", "data": {"year": {"32": [2025]}}},
        "https://static-data.gaokao.cn/www/2.0/yk/school/118/dic/specialplan.json",
        {
            "school_id": 1,
            "school_name": "苏州大学",
            "gaokao_school_id": "118",
            "provinces": [{"id": 7, "name": "江苏", "code": "32"}],
            "years": ["2025", 2024, 2025, None, "bad"],
        },
    )

    requests = asyncio.run(_collect(spider.parse_plan_dictionary(response)))

    assert [request.url for request in requests] == [
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2025/32.json",
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2024/32.json",
    ]
    assert [request.meta["year"] for request in requests] == [2025, 2024]


def test_parse_gaokao_static_enrollment_plan_json() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {
            "code": "0000",
            "data": {
                "2074_14_426217": {
                    "numFound": 1,
                    "item": [
                        {
                            "school_id": "118",
                            "special_id": "5647",
                            "type": "2074",
                            "batch": "14",
                            "num": 40,
                            "province": "32",
                            "length": "五年",
                            "tuition": "26400",
                            "remark": "",
                            "info": "(与加拿大维多利亚大学合作)(中外合作办学)",
                            "special_group": "426217",
                            "sg_name": "(13)",
                            "sg_info": "首选历史,再选不限",
                            "spcode": "020301K",
                            "spname": "金融学(与加拿大维多利亚大学合作)(中外合作办学)",
                            "sp_name": "金融学",
                            "local_batch_name": "本科批",
                            "zslx_name": "普通类",
                        }
                    ],
                }
            },
        },
        "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2025/32.json",
        {
            "school_id": 1,
            "school_name": "苏州大学",
            "gaokao_school_id": "118",
            "province_id": 7,
            "province_code": "32",
            "year": 2025,
        },
    )
    fake_pool = _FakePool(AsyncMock())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=4)),
        patch(
            "gaokao_vault.spiders.enrollment_plan_spider.find_majors_by_name",
            new=AsyncMock(return_value=[{"id": 88}]),
        ),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["school_id"] == 1
    assert items[0]["province_id"] == 7
    assert items[0]["year"] == 2025
    assert items[0]["subject_category_id"] == 4
    assert items[0]["batch"] == "本科批"
    assert items[0]["major_name"] == "金融学(与加拿大维多利亚大学合作)(中外合作办学)"
    assert items[0]["major_id"] == 88
    assert items[0]["plan_count"] == 40
    assert items[0]["duration"] == "五年"
    assert items[0]["tuition"] == "26400"
    assert items[0]["note"] == "(与加拿大维多利亚大学合作)(中外合作办学)"
    assert items[0]["major_group_code"] == "(13)"
    assert items[0]["major_code_raw"] == "020301K"
    assert items[0]["selection_requirement"] == "首选历史,再选不限"
    assert items[0]["data_source"] == "gaokao.cn"
    assert items[0]["source_url"] == "https://static-data.gaokao.cn/www/2.0/schoolspecialplan/118/2025/32.json"
    process_item.assert_awaited_once()
