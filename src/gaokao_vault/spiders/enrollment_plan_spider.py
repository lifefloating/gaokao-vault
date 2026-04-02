from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.enrollment import upsert_enrollment_plan
from gaokao_vault.models.enrollment import EnrollmentPlanItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

PROVINCE_IDS = list(range(1, 32))
YEAR_START = 2020
YEAR_END = datetime.now().year


class EnrollmentPlanSpider(BaseGaokaoSpider):
    """Crawl enrollment plans: school x province x year."""

    name: str = "enrollment_plan_spider"
    task_type: str = TaskType.ENROLLMENT_PLANS

    concurrent_requests = 3
    download_delay = 2.0

    async def start_requests(self):
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            for province_id in PROVINCE_IDS:
                for year in range(YEAR_START, YEAR_END + 1):
                    url = f"{BASE_URL}/sch/schoolInfo--schId-{sch_id}.dhtml"
                    yield Request(
                        url,
                        callback=self.parse,
                        meta={
                            "school_id": school_id,
                            "province_id": province_id,
                            "year": year,
                        },
                        params={
                            "provinceId": str(province_id),
                            "year": str(year),
                            "tab": "plan",
                        },
                    )

    async def parse(self, response: Response):
        if response.request is None:
            return
        school_id = response.request.meta.get("school_id")
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")

        if not school_id or not province_id or not year:
            return

        for row in response.css("table.plan-table tr"):
            cells = row.css("td")
            if len(cells) < 3:
                continue

            major_name = cells[0].css("::text").get("").strip()
            batch = cells[1].css("::text").get("").strip() if len(cells) > 1 else None
            plan_text = cells[2].css("::text").get("").strip() if len(cells) > 2 else ""
            duration = cells[3].css("::text").get("").strip() if len(cells) > 3 else None
            tuition = cells[4].css("::text").get("").strip() if len(cells) > 4 else None

            if not major_name:
                continue

            plan_count = int(plan_text) if plan_text.isdigit() else None

            data = {
                "school_id": school_id,
                "province_id": province_id,
                "year": year,
                "batch": batch,
                "major_name": major_name,
                "plan_count": plan_count,
                "duration": duration,
                "tuition": tuition,
            }

            item = validate_item(EnrollmentPlanItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="enrollment_plans",
                    unique_keys={
                        "school_id": school_id,
                        "province_id": province_id,
                        "year": year,
                        "major_name": major_name,
                    },
                    upsert_fn=upsert_enrollment_plan,
                )
