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
from gaokao_vault.pipeline.admission_rules import (
    extract_eligibility_requirements,
    extract_physical_exam_or_political_review,
    extract_political_review_requirement,
    extract_program_type,
    extract_service_obligation,
)
from gaokao_vault.pipeline.batch_normalizer import normalize_batch
from gaokao_vault.pipeline.quality import missing_field_flags
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
_DATA_SOURCE = "gaokao.chsi.com.cn"


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
        code: str | None = None,
    ) -> int | None:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        source_id = query.get("specId", [None])[0]
        if source_id:
            row = await find_major_by_source_id(conn, source_id)
            if row is not None:
                return row["id"]

        if code:
            row = await find_major_by_code(conn, code)
            if row is not None:
                return row["id"]

        href_code = self._extract_code_from_href(href)
        if href_code:
            row = await find_major_by_code(conn, href_code)
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
            for table in _candidate_tables(response, "admission-table"):
                header_map: dict[str, int] | None = None
                for row in table.css("tr"):
                    headers = [
                        "".join(part.strip() for part in cell.css("::text").getall() if part.strip())
                        for cell in row.css("th")
                    ]
                    if headers:
                        header_map = {text: idx for idx, text in enumerate(headers)}
                        continue

                    cells = row.css("td")
                    if len(cells) < 5:
                        continue

                    major_idx = _column_index(header_map, ("专业名称", "专业"), 0)
                    subject_idx = _column_index(header_map, ("科类", "选科"), 1)
                    batch_idx = _column_index(header_map, ("批次",), 2)
                    min_score_idx = _column_index(header_map, ("最低分", "最低分数"), 3)
                    min_rank_idx = _column_index(header_map, ("最低位次", "最低排名"), 4)
                    avg_score_idx = _column_index(header_map, ("平均分",), 5)
                    admitted_count_idx = _column_index(header_map, ("录取人数", "录取数"), 6)
                    plan_count_idx = _column_index(header_map, ("计划数", "招生人数"), -1)
                    school_code_idx = _column_index(header_map, ("院校代码", "学校代码"), -1)
                    school_name_idx = _column_index(header_map, ("院校名称", "学校名称"), -1)
                    major_group_idx = _column_index(header_map, ("院校专业组", "专业组", "专业组代码"), -1)
                    major_code_idx = _column_index(header_map, ("专业代码",), -1)
                    campus_idx = _column_index(header_map, ("校区",), -1)
                    remark_idx = _column_index(header_map, ("备注", "说明"), -1)

                    major_link = cells[major_idx].css("a").first if 0 <= major_idx < len(cells) else None
                    href = major_link.attrib.get("href", "").strip() if major_link else ""
                    major_name = _cell_text(cells, major_idx)
                    subject_category_raw = _cell_text(cells, subject_idx)
                    batch_raw = _cell_text(cells, batch_idx)
                    remark = _cell_text(cells, remark_idx)
                    major_code_raw = _cell_text(cells, major_code_idx) or self._extract_code_from_href(href)

                    if not major_name or not batch_raw:
                        continue

                    major_id = await self._resolve_major_id(conn, name=major_name, href=href, code=major_code_raw)
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
                    batch_info = normalize_batch(batch_raw)
                    min_score = _parse_int(_cell_text(cells, min_score_idx) or "")
                    min_rank = _parse_int(_cell_text(cells, min_rank_idx) or "")
                    avg_score = _parse_int(_cell_text(cells, avg_score_idx) or "")
                    admitted_count = _parse_int(_cell_text(cells, admitted_count_idx) or "")
                    plan_count = _parse_int(_cell_text(cells, plan_count_idx) or "")

                    data = {
                        "school_id": school_id,
                        "major_id": major_id,
                        "province_id": province_id,
                        "year": year,
                        "subject_category_id": subject_category_id,
                        "batch": batch_raw,
                        "batch_code": batch_info.code,
                        "batch_category": batch_info.category,
                        "batch_segment": batch_info.segment,
                        "min_score": min_score,
                        "min_rank": min_rank,
                        "avg_score": avg_score,
                        "admitted_count": admitted_count,
                        "plan_count": plan_count,
                        "school_code_raw": _cell_text(cells, school_code_idx),
                        "school_name_raw": _cell_text(cells, school_name_idx),
                        "major_group_code": _cell_text(cells, major_group_idx),
                        "major_code_raw": major_code_raw,
                        "campus": _cell_text(cells, campus_idx),
                        "program_type": extract_program_type(batch_raw, remark),
                        "eligibility_requirements": extract_eligibility_requirements(remark),
                        "physical_exam_or_political_review": extract_physical_exam_or_political_review(remark),
                        "political_review_requirement": extract_political_review_requirement(remark),
                        "service_obligation": extract_service_obligation(remark),
                        "major_name_raw": major_name,
                        "subject_category_raw": subject_category_raw,
                        "batch_raw": batch_raw,
                        "remark": remark,
                        "source_url": response.url,
                        "data_source": _DATA_SOURCE,
                    }
                    data["quality_flags"] = missing_field_flags(data, ("min_score", "min_rank", "admitted_count"))

                    item = validate_item(MajorAdmissionResultItem, data)
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


def _column_index(header_map: dict[str, int] | None, candidates: tuple[str, ...], default: int) -> int:
    if header_map is None:
        return default
    for candidate in candidates:
        if candidate in header_map:
            return header_map[candidate]
    return default


def _candidate_tables(response: Response, class_name: str):
    tables = response.css(f"table.{class_name}")
    return tables if tables else response.css("table")


def _cell_text(cells, index: int) -> str | None:
    if index < 0 or index >= len(cells):
        return None
    text = "".join(part.strip() for part in cells[index].css("::text").getall() if part.strip())
    return text or None
