from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.admission import upsert_major_admission_result
from gaokao_vault.db.queries.majors import find_major_by_code, find_major_by_source_id, find_majors_by_name
from gaokao_vault.models.admission import MajorAdmissionResultItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.scope import iter_crawl_years, load_province_targets

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

_HREF_CODE_PATTERN = re.compile(r"(?:code|zydm|specialityCode)-([A-Za-z0-9]+)")
_ADMISSION_RESULT_URL_TEMPLATE = (
    f"{BASE_URL}/sch/schoolInfo--schId-{{sch_id}}.dhtml?provinceId={{province_id}}&year={{year}}&tab=score"
)
_YEAR_START = 2020
_YEAR_END = datetime.now().year


class MajorAdmissionResultSpider(BaseGaokaoSpider):
    name: str = "major_admission_result_spider"
    task_type: str = TaskType.MAJOR_ADMISSION_RESULTS

    async def _load_latest_task_status(self, pool: asyncpg.Pool, task_type: str) -> asyncpg.Record | None:
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT status, failed_items, finished_at
                FROM crawl_tasks
                WHERE task_type = $1
                ORDER BY id DESC
                LIMIT 1
                """,
                task_type,
            )

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
        return None

    async def _resolve_major_id(
        self,
        conn: asyncpg.Connection,
        *,
        name: str | None,
        href: str,
    ) -> int | None:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        source_id = query.get("specId", [None])[0]
        if source_id:
            row = await find_major_by_source_id(conn, source_id)
            if row is not None:
                return row["id"]

        code = self._extract_code_from_href(href)
        if code:
            row = await find_major_by_code(conn, code)
            if row is not None:
                return row["id"]

        if name:
            rows = await find_majors_by_name(conn, name)
            if len(rows) == 1:
                return rows[0]["id"]

        return None

    async def start_requests(self):
        try:
            pool = await self._get_pool()
            schools_row = await self._load_latest_task_status(pool, TaskType.SCHOOLS)
            majors_row = await self._load_latest_task_status(pool, TaskType.MAJORS)

            schools_stable = bool(
                schools_row
                and schools_row["status"] == "success"
                and schools_row["failed_items"] == 0
                and schools_row["finished_at"] is not None
            )
            majors_stable = bool(
                majors_row
                and majors_row["status"] == "success"
                and majors_row["failed_items"] == 0
                and majors_row["finished_at"] is not None
            )
        except Exception:
            logger.warning("Failed to verify upstream task stability for major admission results", exc_info=True)
            return

        if not schools_stable or not majors_stable:
            logger.warning(
                "Skipping major_admission_results crawl because upstream tasks are not stable (schools=%s majors=%s)",
                schools_stable,
                majors_stable,
            )
            return

        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        provinces = await load_province_targets(pool)
        years = iter_crawl_years(mode=self.mode, full_start_year=_YEAR_START, current_year=_YEAR_END)

        for row in rows:
            for province in provinces:
                for year in years:
                    yield Request(
                        _ADMISSION_RESULT_URL_TEMPLATE.format(
                            sch_id=row["sch_id"],
                            province_id=province.url_value,
                            year=year,
                        ),
                        callback=self.parse,
                        meta={
                            "school_id": row["id"],
                            "province_id": province.id,
                            "province_code": province.url_value,
                            "year": year,
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

        async with (await self._get_pool()).acquire() as conn:
            for row in response.css("table.admission-table tr"):
                cells = row.css("td")
                if len(cells) < 5:
                    continue

                major_link = cells[0].css("a").first
                href = major_link.attrib.get("href", "").strip() if major_link else ""
                major_name = "".join(part.strip() for part in cells[0].css("::text").getall() if part.strip()) or None
                subject_category_raw = cells[1].css("::text").get("").strip() or None
                batch_raw = cells[2].css("::text").get("").strip() or None

                if not major_name or not batch_raw:
                    continue

                major_id = await self._resolve_major_id(conn, name=major_name, href=href)
                if major_id is None:
                    logger.warning(
                        "Unable to resolve major in admission results school_id=%s province_id=%s year=%s name=%s href=%s",
                        school_id,
                        province_id,
                        year,
                        major_name,
                        href,
                    )
                    continue

                subject_category_id = await self._resolve_subject_category(subject_category_raw or "")
                min_score = _parse_int(cells[3].css("::text").get("").strip())
                min_rank = _parse_int(cells[4].css("::text").get("").strip())
                avg_score = _parse_int(cells[5].css("::text").get("").strip()) if len(cells) > 5 else None
                admitted_count = _parse_int(cells[6].css("::text").get("").strip()) if len(cells) > 6 else None

                item = validate_item(
                    MajorAdmissionResultItem,
                    {
                        "school_id": school_id,
                        "major_id": major_id,
                        "province_id": province_id,
                        "year": year,
                        "subject_category_id": subject_category_id,
                        "batch": batch_raw,
                        "min_score": min_score,
                        "min_rank": min_rank,
                        "avg_score": avg_score,
                        "admitted_count": admitted_count,
                        "major_name_raw": major_name,
                        "subject_category_raw": subject_category_raw,
                        "batch_raw": batch_raw,
                        "source_url": response.url,
                    },
                )
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="major_admission_results",
                        unique_keys={
                            "school_id": school_id,
                            "major_id": major_id,
                            "province_id": province_id,
                            "year": year,
                            "subject_category_id": subject_category_id,
                            "batch": batch_raw,
                        },
                        upsert_fn=upsert_major_admission_result,
                    )


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None
