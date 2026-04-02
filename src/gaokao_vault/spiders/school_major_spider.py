from __future__ import annotations

import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import upsert_school_major
from gaokao_vault.models.major import SchoolMajorItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)


class SchoolMajorSpider(BaseGaokaoSpider):
    """Crawl school-major associations from school detail pages."""

    name: str = "school_major_spider"
    task_type: str = TaskType.SCHOOL_MAJORS

    async def start_requests(self):
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            url = f"{BASE_URL}/sch/schoolInfo--schId-{sch_id}.dhtml"
            yield Request(
                url,
                callback=self.parse,
                meta={"school_id": school_id, "sch_id": sch_id},
            )

    async def parse(self, response: Response):
        if response.status == 404:
            return

        if response.request is None:
            return
        school_id = response.request.meta.get("school_id")

        for link in response.css("div.major-list a.major-link"):
            major_code = link.attrib.get("data-code", "").strip()
            if not major_code:
                continue

            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id FROM majors WHERE code = $1", major_code)

            if not row:
                continue

            major_id = row["id"]
            data = {"school_id": school_id, "major_id": major_id}

            item = validate_item(SchoolMajorItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="school_majors",
                    unique_keys={"school_id": school_id, "major_id": major_id},
                    upsert_fn=upsert_school_major,
                )
