from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.major_admission_result_spider import MajorAdmissionResultSpider


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


class _FakeTaskStatusConnection:
    def __init__(
        self,
        task_rows: dict[str, dict | None],
        schools: list[dict] | None = None,
        provinces: list[dict] | None = None,
    ) -> None:
        self.task_rows = task_rows
        self.schools = schools or []
        self.provinces = provinces or []
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, _query: str, task_type: str):
        return self.task_rows.get(task_type)

    async def fetch(self, query: str, *args: object):
        self.fetch_calls.append((query, args))
        if "FROM schools ORDER BY id" in query:
            return self.schools
        if "FROM provinces ORDER BY id" in query:
            return self.provinces
        return []


class _FakeMajorLookupConnection:
    def __init__(self) -> None:
        self.rows = [{"id": 12}]

    async def fetch(self, query: str, value: str):
        if "FROM majors WHERE name" in query and value == "计算机科学与技术":
            return self.rows
        return []


def _make_spider() -> MajorAdmissionResultSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return MajorAdmissionResultSpider(db_config=db_config, crawl_task_id=1)


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


_ADMISSION_HTML = """
<html>
  <body>
    <table class="admission-table">
      <tr>
        <th>专业</th>
        <th>科类</th>
        <th>批次</th>
        <th>最低分</th>
        <th>最低位次</th>
        <th>平均分</th>
        <th>录取人数</th>
      </tr>
      <tr>
        <td>计算机科学与技术</td>
        <td>物理类</td>
        <td>本科批</td>
        <td>612</td>
        <td>3456</td>
        <td>618</td>
        <td>8</td>
      </tr>
    </table>
  </body>
</html>
"""

_ENRICHED_ADMISSION_HTML = """
<html>
  <body>
    <table class="admission-table">
      <tr>
        <th>院校代码</th>
        <th>院校名称</th>
        <th>院校专业组</th>
        <th>专业代码</th>
        <th>专业</th>
        <th>科类</th>
        <th>批次</th>
        <th>最低分</th>
        <th>最低位次</th>
        <th>平均分</th>
        <th>录取人数</th>
        <th>计划数</th>
        <th>校区</th>
        <th>备注</th>
      </tr>
      <tr>
        <td>10200</td>
        <td>测试大学</td>
        <td>01</td>
        <td>080901</td>
        <td><a href="/sch/major--code-080901.dhtml">计算机科学与技术</a></td>
        <td>物理类</td>
        <td>提前批普通类A段</td>
        <td>612</td>
        <td>3456</td>
        <td>618</td>
        <td>8</td>
        <td>9</td>
        <td>主校区</td>
        <td>军校,须通过政治考核,毕业后服从分配</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_start_requests_skips_when_upstreams_are_unstable() -> None:
    spider = _make_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "failed", "failed_items": 1, "finished_at": "2026-04-24T00:00:00"},
            "majors": {"status": "success", "failed_items": 0, "finished_at": "2026-04-24T00:00:00"},
        },
    )

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests == []


def test_start_requests_yields_school_requests_when_upstreams_are_stable() -> None:
    spider = _make_spider()
    conn = _FakeTaskStatusConnection(
        task_rows={
            "schools": {"status": "success", "failed_items": 0, "finished_at": "2026-04-24T00:00:00"},
            "majors": {"status": "success", "failed_items": 0, "finished_at": "2026-04-24T00:00:00"},
        },
        schools=[{"id": 1, "sch_id": 34}],
        provinces=[{"id": 7, "name": "吉林", "code": "22"}],
    )

    get_pool = AsyncMock(return_value=_FakePool(conn))
    with patch.object(spider, "_get_pool", new=get_pool):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert len(requests) > 0
    assert get_pool.await_count == 1
    assert requests[0].meta["school_id"] == 1
    assert requests[0].meta["province_id"] == 7
    assert requests[0].meta["province_code"] == "22"
    assert "provinceId=22" in requests[0].url


def test_parse_yields_major_admission_result_items() -> None:
    spider = _make_spider()
    response = _make_response(
        _ADMISSION_HTML,
        "https://gaokao.chsi.com.cn/test",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(_FakeMajorLookupConnection())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["school_id"] == 1
    assert items[0]["major_id"] == 12
    assert items[0]["province_id"] == 7
    assert items[0]["year"] == 2025
    assert items[0]["subject_category_id"] == 3
    assert items[0]["min_score"] == 612
    assert items[0]["min_rank"] == 3456
    assert items[0]["admitted_count"] == 8


def test_parse_major_admission_result_preserves_group_code_campus_and_quality_flags() -> None:
    spider = _make_spider()
    response = _make_response(
        _ENRICHED_ADMISSION_HTML,
        "https://gaokao.chsi.com.cn/test-admission",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(_FakeMajorLookupConnection())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["school_code_raw"] == "10200"
    assert items[0]["school_name_raw"] == "测试大学"
    assert items[0]["major_group_code"] == "01"
    assert items[0]["major_code_raw"] == "080901"
    assert items[0]["campus"] == "主校区"
    assert items[0]["min_rank"] == 3456
    assert items[0]["plan_count"] == 9
    assert items[0]["batch_code"] == "early"
    assert items[0]["batch_category"] == "提前批"
    assert items[0]["batch_segment"] == "A段"
    assert items[0]["program_type"] == "军校"
    assert items[0]["physical_exam_or_political_review"] == "须通过政治考核"
    assert items[0]["political_review_requirement"] == "须通过政治考核"
    assert items[0]["service_obligation"] == "毕业后服从分配"
    assert items[0]["data_source"] == "gaokao.chsi.com.cn"
    assert items[0]["quality_flags"] == []
    process_item.assert_awaited_once()


def test_parse_major_admission_result_accepts_generic_table_with_matching_headers() -> None:
    spider = _make_spider()
    response = _make_response(
        _ADMISSION_HTML.replace('class="admission-table"', ""),
        "https://gaokao.chsi.com.cn/generic-admission",
        {"school_id": 1, "province_id": 7, "year": 2025},
    )
    fake_pool = _FakePool(_FakeMajorLookupConnection())

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=fake_pool)),
        patch.object(spider, "_resolve_subject_category", new=AsyncMock(return_value=3)),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert len(items) == 1
    assert items[0]["major_name_raw"] == "计算机科学与技术"
    assert items[0]["min_score"] == 612
    assert items[0]["source_url"] == "https://gaokao.chsi.com.cn/generic-admission"
    process_item.assert_awaited_once()
