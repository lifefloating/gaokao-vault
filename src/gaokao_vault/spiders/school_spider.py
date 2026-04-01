from __future__ import annotations

import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import upsert_school
from gaokao_vault.models.school import SchoolItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_SCH_ID = 5000


class SchoolSpider(BaseGaokaoSpider):
    name: str = "school_spider"
    task_type: str = TaskType.SCHOOLS

    async def start_requests(self):
        for sch_id in range(1, MAX_SCH_ID + 1):
            url = f"{BASE_URL}/sch/schoolInfo--schId-{sch_id}.dhtml"
            yield Request(url, callback=self.parse, meta={"sch_id": sch_id})

    async def parse(self, response: Response):
        if response.status == 404:
            return

        sch_id = response.request.meta.get("sch_id", 0)

        name_el = response.css("h1.yxk-name::text")
        name = name_el.get("").strip() if name_el else ""
        if not name:
            logger.debug("No school name found for schId=%d", sch_id)
            return

        data = {
            "sch_id": sch_id,
            "name": name,
        }

        # Extract basic info from detail table
        for row in response.css("table.yxk-detail tr"):
            label_el = row.css("th::text")
            value_el = row.css("td::text")
            if not label_el or not value_el:
                continue
            label = label_el.get("").strip()
            value = value_el.get("").strip()
            if not label or not value:
                continue

            field_map = {
                "所在地": "city",
                "隶属于": "authority",
                "办学层次": "level",
                "院校类型": "school_type",
                "官方网址": "website",
                "招办电话": "phone",
                "电子邮箱": "email",
                "通讯地址": "address",
            }
            if label in field_map:
                data[field_map[label]] = value

        # Extract boolean tags
        tags_text = response.css(".yxk-tags span::text").getall()
        tag_set = {t.strip() for t in tags_text}
        data["is_211"] = "211" in tag_set
        data["is_985"] = "985" in tag_set
        data["is_double_first"] = "双一流" in tag_set
        data["is_private"] = "民办" in tag_set
        data["is_independent"] = "独立学院" in tag_set
        data["is_sino_foreign"] = "中外合作办学" in tag_set

        # Extract logo
        logo_el = response.css("img.yxk-logo::attr(src)")
        if logo_el:
            data["logo_url"] = logo_el.get("")

        # Extract introduction
        intro_el = response.css("div.yxk-intro")
        if intro_el:
            data["introduction"] = intro_el.get("").strip()[:5000]

        item = validate_item(SchoolItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="schools",
                unique_keys={"sch_id": sch_id},
                upsert_fn=upsert_school,
            )
