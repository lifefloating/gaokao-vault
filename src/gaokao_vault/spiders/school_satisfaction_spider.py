from __future__ import annotations

import json
import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import upsert_school_satisfaction
from gaokao_vault.models.school import SchoolSatisfactionItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)


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
            url = f"{BASE_URL}/zyk/pub/myd/?schId={sch_id}&type=school"
            yield Request(
                url,
                callback=self.parse,
                meta={"school_id": school_id},
            )

    async def parse(self, response: Response):
        if response.request is None:
            return
        school_id = response.request.meta.get("school_id")

        try:
            result = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Invalid JSON response for school_id=%d", school_id)
            return

        if not isinstance(result, dict):
            return

        data_list = result.get("data", [result])
        if isinstance(data_list, dict):
            data_list = [data_list]

        for entry in data_list:
            data = {
                "school_id": school_id,
                "year": entry.get("year"),
                "overall_score": _safe_float(entry.get("overall")),
                "environment_score": _safe_float(entry.get("environment")),
                "life_score": _safe_float(entry.get("life")),
                "vote_count": _safe_int(entry.get("votes")),
            }

            item = validate_item(SchoolSatisfactionItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="school_satisfaction",
                    unique_keys={"school_id": school_id, "year": data.get("year")},
                    upsert_fn=upsert_school_satisfaction,
                )


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
