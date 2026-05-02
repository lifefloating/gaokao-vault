from __future__ import annotations

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from gaokao_vault.config import DatabaseConfig
from gaokao_vault.spiders.school_satisfaction_spider import SchoolSatisfactionSpider


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
    async def fetch(self, query: str, *_args):
        if "FROM schools" in query:
            return [{"id": 102, "sch_id": 35}]
        return []


def _make_spider() -> SchoolSatisfactionSpider:
    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return SchoolSatisfactionSpider(db_config=db_config, crawl_task_id=1)


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


def test_start_requests_uses_appraisal_info_api() -> None:
    spider = _make_spider()

    with patch.object(spider, "_get_pool", new=AsyncMock(return_value=_FakePool(_FakeConnection()))):
        requests = asyncio.run(_collect(spider.start_requests()))

    assert len(requests) == 1
    assert requests[0].url == "https://gaokao.chsi.com.cn/zyk/pub/appraisalinfo/35"
    assert requests[0].callback == spider.parse
    assert requests[0].meta == {"school_id": 102, "sch_id": 35}


def test_parse_appraisal_info_persists_school_satisfaction_scores() -> None:
    spider = _make_spider()
    response = _make_json_response(
        {
            "flag": True,
            "msg": {
                "schappraisalinfo": [
                    {"type": "综合", "avgRank": 4.0, "count": 2220},
                    {"type": "院校", "avgRank": 4.1, "count": 2643},
                    {"type": "生活", "avgRank": 3.8, "count": 2099},
                ]
            },
        },
        "https://gaokao.chsi.com.cn/zyk/pub/appraisalinfo/35",
        {"school_id": 102, "sch_id": 35},
    )

    with (
        patch("gaokao_vault.spiders.school_satisfaction_spider._snapshot_year", return_value=2026),
        patch.object(spider, "process_item", new=AsyncMock(return_value="new")) as process_item,
    ):
        items = asyncio.run(_collect(spider.parse(response)))

    assert items == [
        {
            "school_id": 102,
            "year": 2026,
            "overall_score": 4.0,
            "environment_score": 4.1,
            "life_score": 3.8,
            "vote_count": 2220,
        }
    ]
    process_item.assert_awaited_once_with(
        items[0],
        entity_type="school_satisfaction",
        unique_keys={"school_id": 102, "year": 2026},
        upsert_fn=ANY,
    )
