from __future__ import annotations

import json
import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import upsert_major_satisfaction
from gaokao_vault.models.major import MajorSatisfactionItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)


class MajorSatisfactionSpider(BaseGaokaoSpider):
    """Crawl major satisfaction scores via API/JSON responses."""

    name: str = "major_satisfaction_spider"
    task_type: str = TaskType.MAJOR_SATISFACTION

    async def start_requests(self):
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT m.id as major_id, s.id as school_id, s.sch_id "
                "FROM majors m CROSS JOIN schools s ORDER BY m.id, s.id"
            )

        for row in rows:
            major_id = row["major_id"]
            school_id = row["school_id"]
            sch_id = row["sch_id"]
            url = f"{BASE_URL}/zyk/pub/myd/"
            yield Request(
                url,
                callback=self.parse,
                meta={"major_id": major_id, "school_id": school_id},
                params={
                    "schId": str(sch_id),
                    "majorId": str(major_id),
                    "type": "major",
                },
            )

    async def parse(self, response: Response):
        major_id = response.request.meta.get("major_id")
        school_id = response.request.meta.get("school_id")

        try:
            result = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(result, dict):
            return

        overall = result.get("overall") or result.get("data", {}).get("overall")
        votes = result.get("votes") or result.get("data", {}).get("votes")

        data = {
            "major_id": major_id,
            "school_id": school_id,
            "overall_score": _safe_float(overall),
            "vote_count": _safe_int(votes),
        }

        item = validate_item(MajorSatisfactionItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="major_satisfaction",
                unique_keys={"major_id": major_id, "school_id": school_id},
                upsert_fn=upsert_major_satisfaction,
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
