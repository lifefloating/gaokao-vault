from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import (
    find_major_by_code,
    find_majors_by_name,
    upsert_school_major,
)
from gaokao_vault.models.major import SchoolMajorItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)
_HREF_CODE_PATTERN = re.compile(r"(?:code|zydm|specialityCode)-([A-Za-z0-9]+)")


class SchoolMajorSpider(BaseGaokaoSpider):
    """Crawl school-major associations from school detail pages."""

    name: str = "school_major_spider"
    task_type: str = TaskType.SCHOOL_MAJORS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._allow_name_fallback = False

    async def _load_name_fallback_policy(self) -> bool:
        async with (await self._get_pool()).acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, failed_items FROM crawl_tasks WHERE task_type = $1 ORDER BY id DESC LIMIT 1",
                TaskType.MAJORS,
            )
        return bool(row and row["status"] == "success" and row["failed_items"] == 0)

    @staticmethod
    def _extract_code_from_href(href: str) -> str | None:
        if not href:
            return None

        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        for key in ("code", "zydm", "specialityCode"):
            values = query.get(key)
            if values and values[0].strip():
                return values[0].strip()

        match = _HREF_CODE_PATTERN.search(href)
        if match:
            return match.group(1)

        path_tail = parsed.path.rstrip("/").split("/")[-1]
        if re.fullmatch(r"[A-Za-z0-9]{4,}", path_tail):
            return path_tail

        return None

    def _extract_major_candidates(self, response: Response) -> list[dict[str, str | None]]:
        candidates: list[dict[str, str | None]] = []
        for link in response.css("div.major-list a.major-link"):
            href = link.attrib.get("href", "").strip()
            name_parts = [part.strip() for part in link.css("::text").getall() if part.strip()]
            name = name_parts[0] if name_parts else None
            data_code = link.attrib.get("data-code", "").strip() or None
            href_code = self._extract_code_from_href(href)
            candidates.append(
                {
                    "data_code": data_code,
                    "href_code": href_code,
                    "name": name,
                    "href": href or None,
                }
            )
        return candidates

    async def _resolve_major_id(
        self,
        conn,
        *,
        school_id: int,
        sch_id: int,
        data_code: str | None,
        href_code: str | None,
        name: str | None,
        page_url: str,
    ) -> int | None:
        for code in dict.fromkeys(code for code in (data_code, href_code) if code):
            row = await find_major_by_code(conn, code)
            if row is not None:
                return row["id"]

        if name and self._allow_name_fallback:
            rows = await find_majors_by_name(conn, name)
            if len(rows) == 1:
                return rows[0]["id"]
            if len(rows) > 1:
                logger.warning(
                    "Ambiguous major match school_id=%s sch_id=%s data_code=%s href_code=%s name=%s url=%s",
                    school_id,
                    sch_id,
                    data_code,
                    href_code,
                    name,
                    page_url,
                )
                return None

        if name and not self._allow_name_fallback:
            logger.warning(
                "Name fallback disabled school_id=%s sch_id=%s data_code=%s href_code=%s name=%s url=%s",
                school_id,
                sch_id,
                data_code,
                href_code,
                name,
                page_url,
            )
            return None

        logger.warning(
            "Unable to resolve major school_id=%s sch_id=%s data_code=%s href_code=%s name=%s url=%s",
            school_id,
            sch_id,
            data_code,
            href_code,
            name,
            page_url,
        )
        return None

    async def start_requests(self):
        try:
            self._allow_name_fallback = await self._load_name_fallback_policy()
        except Exception:
            logger.warning("Failed to load name fallback policy for school majors", exc_info=True)
            self._allow_name_fallback = False

        async with (await self._get_pool()).acquire() as conn:
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
        sch_id = response.request.meta.get("sch_id")
        if not school_id or not sch_id:
            return

        async with (await self._get_pool()).acquire() as conn:
            for candidate in self._extract_major_candidates(response):
                major_id = await self._resolve_major_id(
                    conn,
                    school_id=school_id,
                    sch_id=sch_id,
                    data_code=candidate["data_code"],
                    href_code=candidate["href_code"],
                    name=candidate["name"],
                    page_url=response.url,
                )
                if major_id is None:
                    continue

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
