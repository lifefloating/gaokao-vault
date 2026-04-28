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


def test_start_requests_uses_province_code_for_remote_url_and_local_id_for_storage() -> None:
    spider = _make_spider()
    spider.mode = "incremental"

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeStartConnection()))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert requests
    assert requests[0].meta["province_id"] == 7
    assert requests[0].meta["province_code"] == "22"
    assert "provinceId=22" in requests[0].url
