from __future__ import annotations

import logging
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import upsert_major_interpretation
from gaokao_vault.models.major import MajorInterpretationItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_PAGES = 50


class InterpretationSpider(BaseGaokaoSpider):
    """Crawl major interpretation articles: list + detail pages."""

    name: str = "interpretation_spider"
    task_type: str = TaskType.INTERPRETATIONS

    async def start_requests(self):
        url = f"{BASE_URL}/zyk/zybk/zyjd/"
        yield Request(url, callback=self.parse, meta={"page": 1})

    async def parse(self, response: Response):
        if response.request is None:
            return
        current_page = response.request.meta.get("page", 1)
        items_found = False

        for item_el in response.css("ul.article-list li"):
            items_found = True

            link = item_el.css("a")
            if not link:
                continue

            title = link.css("::text").get("").strip()
            href = link[0].attrib.get("href", "")
            author = item_el.css("span.author::text").get("").strip() or None
            date_text = item_el.css("span.date::text").get("").strip()
            major_name = item_el.css("span.major::text").get("").strip()

            if not title or not href:
                continue

            yield Request(
                response.urljoin(href),
                callback=self.parse_detail,
                meta={
                    "title": title,
                    "author": author,
                    "publish_date": date_text,
                    "major_name": major_name,
                    "source_url": response.urljoin(href),
                },
            )

        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/zyk/zybk/zyjd/?page={next_page}"
            yield Request(
                url,
                callback=self.parse,
                meta={"page": next_page},
            )

    async def parse_detail(self, response: Response):
        if response.request is None:
            return
        meta = response.request.meta
        major_name = meta.get("major_name", "")

        content_el = response.css("div.article-content")
        content = content_el.get("").strip()[:10000] if content_el else ""

        if not content:
            return

        # Resolve major_id from major name
        major_id = None
        if major_name:
            async with (await self._get_pool()).acquire() as conn:
                row = await conn.fetchrow("SELECT id FROM majors WHERE name = $1", major_name)
                if row:
                    major_id = row["id"]

        publish_date = _parse_date(meta.get("publish_date", ""))

        data = {
            "major_id": major_id,
            "title": meta.get("title"),
            "content": content,
            "author": meta.get("author"),
            "publish_date": publish_date,
            "source_url": meta.get("source_url"),
        }

        item = validate_item(MajorInterpretationItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="major_interpretations",
                unique_keys={
                    "major_id": major_id,
                    "title": meta.get("title", ""),
                },
                upsert_fn=upsert_major_interpretation,
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
