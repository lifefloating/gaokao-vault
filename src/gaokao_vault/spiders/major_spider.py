from __future__ import annotations

import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import (
    upsert_major,
    upsert_major_category,
    upsert_major_subcategory,
)
from gaokao_vault.models.major import MajorCategoryItem, MajorItem, MajorSubcategoryItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

EDUCATION_LEVELS = ["本科", "专科"]


class MajorSpider(BaseGaokaoSpider):
    """Two-phase spider: category list -> major details."""

    name: str = "major_spider"
    task_type: str = TaskType.MAJORS

    async def start_requests(self):
        for level in EDUCATION_LEVELS:
            url = f"{BASE_URL}/zyk/zybk/"
            yield Request(
                url,
                callback=self.parse_categories,
                meta={"education_level": level},
                params={"eduLevel": level},
            )

    async def parse_categories(self, response: Response):
        """Phase 1: Parse category and subcategory lists, then follow to detail pages."""
        if response.request is None:
            return
        education_level = response.request.meta.get("education_level", "本科")

        for cat_el in response.css("div.category-group"):
            cat_name_el = cat_el.css("h3::text")
            cat_code_el = cat_el.css("h3 span.code::text")
            cat_name = cat_name_el.get("").strip() if cat_name_el else ""
            cat_code = cat_code_el.get("").strip() if cat_code_el else None

            if not cat_name:
                continue

            cat_data = validate_item(
                MajorCategoryItem,
                {"name": cat_name, "education_level": education_level, "code": cat_code},
            )
            if cat_data:
                async with (await self._get_pool()).acquire() as conn:
                    cat_id = await upsert_major_category(conn, cat_data)

                for sub_el in cat_el.css("div.subcategory"):
                    sub_name_el = sub_el.css("h4::text")
                    sub_code_el = sub_el.css("h4 span.code::text")
                    sub_name = sub_name_el.get("").strip() if sub_name_el else ""
                    sub_code = sub_code_el.get("").strip() if sub_code_el else None

                    if not sub_name:
                        continue

                    sub_data = validate_item(
                        MajorSubcategoryItem,
                        {"category_id": cat_id, "name": sub_name, "code": sub_code},
                    )
                    if sub_data:
                        async with (await self._get_pool()).acquire() as conn:
                            sub_id = await upsert_major_subcategory(conn, sub_data)

                        for link in sub_el.css("a.major-link"):
                            href = link.attrib.get("href", "")
                            major_name = link.css("::text").get("").strip()
                            if href:
                                yield Request(
                                    response.urljoin(href),
                                    callback=self.parse_major_detail,
                                    meta={
                                        "education_level": education_level,
                                        "subcategory_id": sub_id,
                                        "major_name": major_name,
                                    },
                                )

    async def parse_major_detail(self, response: Response):
        """Phase 2: Parse individual major detail page."""
        if response.request is None:
            return
        meta = response.request.meta
        education_level = meta.get("education_level", "本科")
        subcategory_id = meta.get("subcategory_id")

        name_el = response.css("h1.zy-name::text")
        name = name_el.get("").strip() if name_el else meta.get("major_name", "")

        if not name:
            return

        # Extract source_id from URL
        source_id = response.url.rstrip("/").split("/")[-1] if response.url else None

        data = {
            "source_id": source_id,
            "subcategory_id": subcategory_id,
            "name": name,
            "education_level": education_level,
        }

        # Extract detail fields
        for row in response.css("div.zy-detail-item"):
            label_el = row.css("span.label::text")
            value_el = row.css("span.value::text")
            if not label_el or not value_el:
                continue
            label = label_el.get("").strip()
            value = value_el.get("").strip()

            field_map = {
                "专业代码": "code",
                "修业年限": "duration",
                "授予学位": "degree",
                "就业率": "employment_rate",
            }
            if label in field_map:
                data[field_map[label]] = value

        # Extract description
        desc_el = response.css("div.zy-description")
        if desc_el:
            data["description"] = desc_el.get("").strip()[:5000]

        # Extract graduate directions
        grad_el = response.css("div.zy-graduate")
        if grad_el:
            data["graduate_directions"] = grad_el.get("").strip()[:2000]

        item = validate_item(MajorItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="majors",
                unique_keys={"code": item.get("code"), "education_level": education_level},
                upsert_fn=upsert_major,
            )
