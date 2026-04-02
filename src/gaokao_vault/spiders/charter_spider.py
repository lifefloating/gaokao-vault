from __future__ import annotations

import logging
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.enrollment import upsert_charter
from gaokao_vault.models.enrollment import CharterItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_PAGES = 50


class CharterSpider(BaseGaokaoSpider):
    """Crawl admission charters: list pages + detail pages."""

    name: str = "charter_spider"
    task_type: str = TaskType.CHARTERS

    async def start_requests(self):
        url = f"{BASE_URL}/zsgs/zhangcheng/"
        yield Request(url, callback=self.parse, meta={"page": 1})

    async def parse(self, response: Response):
        if response.request is None:
            return
        current_page = response.request.meta.get("page", 1)
        items_found = False

        for item_el in response.css("ul.charter-list li"):
            items_found = True

            link = item_el.css("a")
            if not link:
                continue

            title = link.css("::text").get("").strip()
            href = link[0].attrib.get("href", "")
            school_name = item_el.css("span.school::text").get("").strip()
            year_text = item_el.css("span.year::text").get("").strip()
            date_text = item_el.css("span.date::text").get("").strip()

            if not title or not href:
                continue

            year = int(year_text) if year_text.isdigit() else datetime.now().year

            yield Request(
                response.urljoin(href),
                callback=self.parse_detail,
                meta={
                    "title": title,
                    "school_name": school_name,
                    "year": year,
                    "publish_date": date_text,
                    "source_url": response.urljoin(href),
                },
            )

        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/zsgs/zhangcheng/"
            yield Request(
                url,
                callback=self.parse,
                meta={"page": next_page},
                params={"page": str(next_page)},
            )

    async def parse_detail(self, response: Response):
        if response.request is None:
            return
        meta = response.request.meta
        school_name = meta.get("school_name", "")

        # Resolve school_id from school name
        school_id = None
        if school_name:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id FROM schools WHERE name = $1", school_name)
                if row:
                    school_id = row["id"]

        if school_id is None:
            logger.debug("School not found: %s", school_name)
            return

        content_el = response.css("div.article-content")
        content = content_el.get("").strip()[:20000] if content_el else ""

        if not content:
            return

        publish_date = _parse_date(meta.get("publish_date", ""))

        data = {
            "school_id": school_id,
            "year": meta.get("year"),
            "title": meta.get("title"),
            "content": content,
            "publish_date": publish_date,
            "source_url": meta.get("source_url"),
        }

        item = validate_item(CharterItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="charters",
                unique_keys={"school_id": school_id, "year": meta.get("year")},
                upsert_fn=upsert_charter,
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
