from __future__ import annotations

import logging
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.special import upsert_special_enrollment
from gaokao_vault.models.special import SpecialEnrollmentItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

ENROLLMENT_TYPES = [
    "自主招生",
    "高校专项计划",
    "国家专项计划",
    "地方专项计划",
    "保送生",
    "艺术类",
    "体育类",
    "强基计划",
    "综合评价",
]

MAX_PAGES = 20


class SpecialSpider(BaseGaokaoSpider):
    """Crawl special enrollment types."""

    name: str = "special_spider"
    task_type: str = TaskType.SPECIAL

    async def start_requests(self):
        for etype in ENROLLMENT_TYPES:
            url = f"{BASE_URL}/gkxx/tsbm/"
            yield Request(
                url,
                callback=self.parse,
                meta={"enrollment_type": etype, "page": 1},
                params={"type": etype, "page": "1"},
            )

    async def parse(self, response: Response):
        if response.request is None:
            return
        etype = response.request.meta.get("enrollment_type")
        current_page = response.request.meta.get("page", 1)
        items_found = False

        for item_el in response.css("ul.news-list li"):
            items_found = True

            link = item_el.css("a")
            if not link:
                continue

            title = link.css("::text").get("").strip()
            href = link[0].attrib.get("href", "")
            date_text = item_el.css("span.date::text").get("").strip()
            year_text = item_el.css("span.year::text").get("").strip()

            if not title:
                continue

            publish_date = _parse_date(date_text)
            year = (
                int(year_text) if year_text.isdigit() else (publish_date.year if publish_date else datetime.now().year)
            )
            source_url = response.urljoin(href) if href else None

            data = {
                "enrollment_type": etype,
                "year": year,
                "title": title,
                "publish_date": publish_date,
                "source_url": source_url,
            }

            if href:
                yield Request(
                    response.urljoin(href),
                    callback=self.parse_detail,
                    meta={"item_data": data},
                )
            else:
                item = validate_item(SpecialEnrollmentItem, data)
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="special_enrollments",
                        unique_keys={
                            "enrollment_type": etype,
                            "year": year,
                            "title": title,
                        },
                        upsert_fn=upsert_special_enrollment,
                    )

        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/gkxx/tsbm/"
            yield Request(
                url,
                callback=self.parse,
                meta={"enrollment_type": etype, "page": next_page},
                params={"type": etype, "page": str(next_page)},
            )

    async def parse_detail(self, response: Response):
        if response.request is None:
            return
        data = response.request.meta.get("item_data", {})
        content_el = response.css("div.article-content")
        if content_el:
            data["content"] = content_el.get("").strip()[:10000]

        item = validate_item(SpecialEnrollmentItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="special_enrollments",
                unique_keys={
                    "enrollment_type": data.get("enrollment_type"),
                    "year": data.get("year"),
                    "title": data.get("title", ""),
                },
                upsert_fn=upsert_special_enrollment,
            )


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
