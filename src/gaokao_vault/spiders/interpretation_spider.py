from __future__ import annotations

import logging
import re
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import upsert_major_interpretation
from gaokao_vault.models.major import MajorInterpretationItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_PAGES = 50
LIST_PAGE_URL = f"{BASE_URL}/zyk/zybk/zyjd/listPage"
LEGACY_TOPIC_URL = f"{BASE_URL}/gkxx/zybk/zt"


class InterpretationSpider(BaseGaokaoSpider):
    """Crawl major interpretation articles: list + detail pages."""

    name: str = "interpretation_spider"
    task_type: str = TaskType.INTERPRETATIONS

    async def start_requests(self):
        yield Request(LIST_PAGE_URL, callback=self.parse, meta={"page": 1, "entrypoint": "zyjd"})
        yield Request(LEGACY_TOPIC_URL, callback=self.parse, meta={"entrypoint": "legacy_topic"})

    async def parse(self, response: Response):
        if response.request is None:
            return
        current_page = int(response.request.meta.get("page", 1))
        entrypoint = response.request.meta.get("entrypoint")
        items_found = False
        seen_urls: set[str] = set()

        for item_el in self._iter_list_items(response):
            items_found = True

            link = item_el.css("a[href]").first
            if not link:
                continue

            title = _clean_text(" ".join(link.css("::text").getall()))
            href = link.attrib.get("href", "")
            author = _clean_text(item_el.css("span.author::text, .author::text").get("")) or None
            date_text = _clean_text(item_el.css("span.date::text, .date::text, .time::text").get(""))
            major_name = _clean_text(item_el.css("span.major::text, .major::text, .zy-name::text, .zymc::text").get(""))

            if not title or not href or not _is_interpretation_href(href):
                continue

            detail_url = response.urljoin(href)
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            yield Request(
                detail_url,
                callback=self.parse_detail,
                meta={
                    "title": title,
                    "author": author,
                    "publish_date": date_text,
                    "major_name": major_name,
                    "source_url": detail_url,
                },
            )

        if entrypoint == "zyjd" and items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{LIST_PAGE_URL}?page={next_page}"
            yield Request(
                url,
                callback=self.parse,
                meta={"page": next_page, "entrypoint": "zyjd"},
            )

    async def parse_detail(self, response: Response):
        if response.request is None:
            return
        meta = response.request.meta
        title = _clean_text(str(meta.get("title") or "")) or _extract_title(response)
        major_name = _clean_text(str(meta.get("major_name") or "")) or _infer_major_name(title)

        content = _extract_content(response)

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
            "title": title,
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

    @staticmethod
    def _iter_list_items(response: Response):
        selectors = (
            "ul.article-list li",
            "ul.news-list li",
            ".zyjd-list",
            ".zyjd-list li",
            ".news-list li",
            ".list li",
            "li",
        )
        seen: set[int] = set()
        for selector in selectors:
            for item_el in response.css(selector):
                element_id = id(item_el)
                if element_id in seen:
                    continue
                seen.add(element_id)
                yield item_el


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _is_interpretation_href(href: str) -> bool:
    return "/zyk/zybk/zyjd/" in href or "/gkxx/zybk/zt/" in href


def _extract_title(response: Response) -> str | None:
    for selector in ("h1::text", ".article-title::text", ".content-title::text", "title::text"):
        title = _clean_text(response.css(selector).get(""))
        if title:
            return title
    return None


def _infer_major_name(title: str | None) -> str:
    if not title:
        return ""
    return re.sub(r"(专业)?解读.*$", "", title).strip()


def _extract_content(response: Response) -> str:
    selectors = (
        "div.article-content",
        ".article-content",
        ".content",
        ".article",
        "#article",
        ".main",
    )
    for selector in selectors:
        content_el = response.css(selector)
        if not content_el:
            continue
        text = _clean_text(" ".join(content_el[0].css("::text").getall()))
        if text:
            return text[:10000]
    return ""
