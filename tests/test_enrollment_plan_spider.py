from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

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
            return [{"id": 1, "sch_id": 34}]
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


def test_start_requests_uses_province_code_for_remote_url_and_local_id_for_storage() -> None:
    spider = _make_spider()
    spider.mode = "incremental"

    get_pool = AsyncMock(return_value=_FakePool(_FakeStartConnection()))
    with patch.object(spider, "_get_pool", new=get_pool):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests
    assert get_pool.await_count == 1
    assert requests[0].meta["province_id"] == 7
    assert requests[0].meta["province_code"] == "22"
    assert "provinceId=22" in requests[0].url
