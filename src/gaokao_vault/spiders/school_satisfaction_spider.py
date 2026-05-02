from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import upsert_school_satisfaction
from gaokao_vault.models.school import SchoolSatisfactionItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.response_utils import response_json

logger = logging.getLogger(__name__)

APPRAISAL_INFO_URL_TEMPLATE = f"{BASE_URL}/zyk/pub/appraisalinfo/{{sch_id}}"


class SchoolSatisfactionSpider(BaseGaokaoSpider):
    """Crawl school satisfaction scores via API/JSON responses."""

    name: str = "school_satisfaction_spider"
    task_type: str = TaskType.SCHOOL_SATISFACTION

    async def start_requests(self):
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            url = APPRAISAL_INFO_URL_TEMPLATE.format(sch_id=sch_id)
            yield Request(
                url,
                callback=self.parse,
                meta={"school_id": school_id, "sch_id": sch_id},
            )

    async def parse(self, response: Response):
        if response.status == 404 or response.request is None:
            return
        school_id = response.request.meta.get("school_id")

        result = response_json(response)
        if result is None:
            logger.debug("Invalid JSON response for school_id=%s", school_id)
            return

        msg = result.get("msg")
        if not isinstance(msg, dict):
            return

        rating_rows = msg.get("schappraisalinfo")
        if not isinstance(rating_rows, list):
            return

        ratings = {entry.get("type"): entry for entry in rating_rows if isinstance(entry, dict)}
        overall = ratings.get("综合")
        environment = ratings.get("院校") or ratings.get("环境")
        life = ratings.get("生活")

        data = {
            "school_id": school_id,
            "year": _snapshot_year(),
            "overall_score": _safe_float(_rating_value(overall, "avgRank")),
            "environment_score": _safe_float(_rating_value(environment, "avgRank")),
            "life_score": _safe_float(_rating_value(life, "avgRank")),
            "vote_count": _safe_int(_rating_value(overall, "count")),
        }
        if data["overall_score"] is None and data["environment_score"] is None and data["life_score"] is None:
            return

        item = validate_item(SchoolSatisfactionItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="school_satisfaction",
                unique_keys={"school_id": school_id, "year": data["year"]},
                upsert_fn=upsert_school_satisfaction,
            )


def _snapshot_year() -> int:
    return datetime.now().year


def _rating_value(entry: dict[str, Any] | None, key: str) -> Any:
    if not entry:
        return None
    return entry.get(key)


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
