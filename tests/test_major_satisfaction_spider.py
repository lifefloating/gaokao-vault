from __future__ import annotations

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from scrapling.fetchers import FetcherSession
from scrapling.parser import Adaptor

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.major_satisfaction_spider import MajorSatisfactionSpider


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
    def __init__(self, *, schools: list[dict] | None = None, majors: list[dict] | None = None) -> None:
        self.schools = schools or []
        self.majors = majors or []
        self.fetch_calls: list[str] = []

    async def fetch(self, query: str, *_args):
        self.fetch_calls.append(query)
        if "FROM schools" in query:
            return self.schools
        if "FROM school_majors" in query:
            if len(_args) >= 2:
                return [major for major in self.majors if major["name"] == _args[1]]
            return self.majors
        return []


def _make_spider() -> MajorSatisfactionSpider:
    def configure_test_sessions(_spider, manager) -> None:
        manager.add("http", FetcherSession())

    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    with patch.object(MajorSatisfactionSpider, "configure_sessions", configure_test_sessions):
        return MajorSatisfactionSpider(db_config=db_config, crawl_task_id=1)


async def _collect(async_gen) -> list:
    items = []
    async for item in async_gen:
        items.append(item)
    return items


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


def test_start_requests_yields_appraisal_info_pages() -> None:
    spider = _make_spider()
    conn = _FakeConnection(schools=[{"id": 102, "sch_id": 35}])

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert len(requests) == 1
    assert requests[0].url == "https://gaokao.chsi.com.cn/zyk/pub/appraisalinfo/35"
    assert requests[0].callback == spider.parse_appraisal_info
    assert requests[0].meta == {"school_id": 102, "sch_id": 35}


def test_parse_appraisal_info_yields_real_satisfaction_pages() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {"flag": True, "msg": {"schDicId": "73394646"}},
        "https://gaokao.chsi.com.cn/zyk/pub/appraisalinfo/35",
        {"school_id": 102, "sch_id": 35},
    )

    requests = asyncio.run(_collect(spider.parse_appraisal_info(response)))

    assert [request.url for request in requests] == [
        "https://gaokao.chsi.com.cn/zyk/pub/myd/specAppraisalTopMore?schId=73394646&type=3&cc=1",
        "https://gaokao.chsi.com.cn/zyk/pub/myd/specAppraisalTopMore?schId=73394646&type=3&cc=2",
    ]
    assert all(request.callback == spider.parse_satisfaction_table for request in requests)
    assert requests[0].meta == {"school_id": 102, "appraisal_sch_id": "73394646", "education_level": "本科"}
    assert requests[1].meta == {"school_id": 102, "appraisal_sch_id": "73394646", "education_level": "专科"}


def test_parse_satisfaction_table_persists_scores_by_school_major_name() -> None:
    spider = _make_spider()
    response = _make_response(
        """
        <html><body>
          <table class="myd-detail-table">
            <tbody>
              <tr>
                <td>法学</td>
                <td><input type="hidden" value="4.5"></td>
                <td><input type="hidden" value="4.1"></td>
                <td><input type="hidden" value="4.5"></td>
                <td><input type="hidden" value="4.3"></td>
              </tr>
              <tr>
                <td>未知专业</td>
                <td><input type="hidden" value="5.0"></td>
              </tr>
            </tbody>
          </table>
        </body></html>
        """,
        "https://gaokao.chsi.com.cn/zyk/pub/myd/specAppraisalTopMore?schId=73394646&type=3&cc=1",
        {"school_id": 102, "appraisal_sch_id": "73394646", "education_level": "本科"},
    )
    conn = _FakeConnection(majors=[{"id": 31, "name": "法学"}])
    process_item = AsyncMock(return_value="new")

    with (
        patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(conn))),
        patch.object(spider, "process_item", new=process_item),
    ):
        items = asyncio.run(_collect(spider.parse_satisfaction_table(response)))

    assert items == [{"major_id": 31, "school_id": 102, "overall_score": 4.5, "vote_count": None}]
    process_item.assert_awaited_once_with(
        {"major_id": 31, "school_id": 102, "overall_score": 4.5, "vote_count": None},
        entity_type="major_satisfaction",
        unique_keys={"major_id": 31, "school_id": 102},
        upsert_fn=ANY,
    )
