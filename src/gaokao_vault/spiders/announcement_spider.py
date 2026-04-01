from __future__ import annotations

import logging
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.special import upsert_announcement
from gaokao_vault.models.special import AnnouncementItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

PROVINCE_IDS = list(range(1, 32))
MAX_PAGES = 20


class AnnouncementSpider(BaseGaokaoSpider):
    """Crawl provincial announcements by 31 provinces."""

    name: str = "announcement_spider"
    task_type: str = TaskType.ANNOUNCEMENTS

    async def start_requests(self):
        for province_id in PROVINCE_IDS:
            url = f"{BASE_URL}/gkxx/zc/ss/"
            yield Request(
                url,
                callback=self.parse,
                meta={"province_id": province_id, "page": 1},
                params={"provinceId": str(province_id), "page": "1"},
            )

    async def parse(self, response: Response):
        province_id = response.request.meta.get("province_id")
        current_page = response.request.meta.get("page", 1)

        if not province_id:
            return

        items_found = False

        for item_el in response.css("ul.news-list li"):
            items_found = True

            link = item_el.css("a")
            if not link:
                continue

            title = link.css("::text").get("").strip()
            href = link.attrib.get("href", "")
            date_text = item_el.css("span.date::text").get("").strip()
            ann_type = item_el.css("span.type::text").get("").strip() or None

            if not title:
                continue

            publish_date = _parse_date(date_text)
            source_url = response.urljoin(href) if href else None

            data = {
                "province_id": province_id,
                "year": publish_date.year if publish_date else None,
                "title": title,
                "announcement_type": ann_type,
                "publish_date": publish_date,
                "source_url": source_url,
            }

            # Follow detail link to get content
            if href:
                yield Request(
                    response.urljoin(href),
                    callback=self.parse_detail,
                    meta={"item_data": data},
                )
            else:
                item = validate_item(AnnouncementItem, data)
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="announcements",
                        unique_keys={
                            "province_id": province_id,
                            "title": title,
                        },
                        upsert_fn=upsert_announcement,
                    )

        # Pagination: follow next page if items were found
        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/gkxx/zc/ss/"
            yield Request(
                url,
                callback=self.parse,
                meta={"province_id": province_id, "page": next_page},
                params={"provinceId": str(province_id), "page": str(next_page)},
            )

    async def parse_detail(self, response: Response):
        """Parse announcement detail page for full content."""
        data = response.request.meta.get("item_data", {})
        province_id = data.get("province_id")

        content_el = response.css("div.article-content")
        if content_el:
            data["content"] = content_el.get("").strip()[:10000]

        item = validate_item(AnnouncementItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="announcements",
                unique_keys={
                    "province_id": province_id,
                    "title": data.get("title", ""),
                },
                upsert_fn=upsert_announcement,
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
