from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.enrollment import upsert_enrollment_plan
from gaokao_vault.db.queries.majors import find_majors_by_name
from gaokao_vault.models.enrollment import EnrollmentPlanItem
from gaokao_vault.pipeline.admission_rules import (
    extract_adjustment_rule,
    extract_eligibility_requirements,
    extract_physical_exam_limit,
    extract_physical_exam_or_political_review,
    extract_political_review_requirement,
    extract_program_type,
    extract_service_obligation,
    extract_single_subject_limit,
)
from gaokao_vault.pipeline.batch_normalizer import normalize_batch
from gaokao_vault.pipeline.quality import missing_field_flags
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.scope import iter_crawl_years, load_province_targets
from gaokao_vault.spiders.table_candidates import candidate_tables

logger = logging.getLogger(__name__)

YEAR_START = 2020
YEAR_END = datetime.now().year
DATA_SOURCE = "gaokao.chsi.com.cn"
_PLAN_TABLE_HEADERS = (
    "专业名称",
    "专业",
    "科类",
    "选科",
    "批次",
    "计划数",
    "学制",
    "学费",
    "备注",
    "说明",
    "院校专业组",
    "专业组",
    "专业组代码",
    "专业代码",
    "选科要求",
    "再选科目",
    "校区",
    "办学地点",
    "就读地点",
)


class EnrollmentPlanSpider(BaseGaokaoSpider):
    """Crawl enrollment plans: school x province x year."""

    name: str = "enrollment_plan_spider"
    task_type: str = TaskType.ENROLLMENT_PLANS

    concurrent_requests = 3
    download_delay = 2.0

    async def start_requests(self):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        provinces = await load_province_targets(pool)
        years = iter_crawl_years(mode=self.mode, full_start_year=YEAR_START, current_year=YEAR_END)

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            for province in provinces:
                for year in years:
                    url = (
                        f"{BASE_URL}/sch/schoolInfo--schId-{sch_id}.dhtml?"
                        f"provinceId={province.url_value}&year={year}&tab=plan"
                    )
                    yield Request(
                        url,
                        callback=self.parse,
                        meta={
                            "school_id": school_id,
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
            for table in candidate_tables(response, "plan-table", _PLAN_TABLE_HEADERS):
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
                    if len(cells) < 3:
                        continue

                    major_name = _cell_text(cells, _column_index(header_map, ("专业名称", "专业"), 0))
                    subject_category_raw = _cell_text(cells, _column_index(header_map, ("科类", "选科"), 1))
                    batch = _cell_text(cells, _column_index(header_map, ("批次",), 2))
                    plan_text = _cell_text(cells, _column_index(header_map, ("计划数",), 3))
                    duration = _cell_text(cells, _column_index(header_map, ("学制",), 4))
                    tuition = _cell_text(cells, _column_index(header_map, ("学费",), 5))
                    note = _cell_text(cells, _column_index(header_map, ("备注", "说明"), 6))
                    major_group_code = _cell_text(
                        cells, _column_index(header_map, ("院校专业组", "专业组", "专业组代码"), -1)
                    )
                    major_code_raw = _cell_text(cells, _column_index(header_map, ("专业代码",), -1))
                    selection_requirement = _cell_text(cells, _column_index(header_map, ("选科要求", "再选科目"), -1))
                    campus = _cell_text(cells, _column_index(header_map, ("校区",), -1))
                    education_location = _cell_text(cells, _column_index(header_map, ("办学地点", "就读地点"), -1))

                    if not major_name:
                        continue

                    major_id = await _resolve_major_id(conn, major_name)
                    subject_category_id = await self._resolve_subject_category(subject_category_raw or "")
                    plan_count = int(plan_text) if plan_text and plan_text.isdigit() else None
                    batch_info = normalize_batch(batch)
                    physical_exam_limit = extract_physical_exam_limit(note)
                    single_subject_limit = extract_single_subject_limit(note)
                    adjustment_rule = extract_adjustment_rule(note)

                    data = {
                        "school_id": school_id,
                        "province_id": province_id,
                        "year": year,
                        "subject_category_id": subject_category_id,
                        "batch": batch,
                        "batch_code": batch_info.code,
                        "batch_category": batch_info.category,
                        "batch_segment": batch_info.segment,
                        "major_name": major_name,
                        "major_id": major_id,
                        "plan_count": plan_count,
                        "duration": duration,
                        "tuition": tuition,
                        "note": note,
                        "major_group_code": major_group_code,
                        "major_code_raw": major_code_raw,
                        "campus": campus,
                        "education_location": education_location,
                        "selection_requirement": selection_requirement,
                        "physical_exam_limit": physical_exam_limit,
                        "single_subject_limit": single_subject_limit,
                        "adjustment_rule": adjustment_rule,
                        "program_type": extract_program_type(batch, note),
                        "eligibility_requirements": extract_eligibility_requirements(note),
                        "physical_exam_or_political_review": extract_physical_exam_or_political_review(note),
                        "political_review_requirement": extract_political_review_requirement(note),
                        "service_obligation": extract_service_obligation(note),
                        "data_source": DATA_SOURCE,
                        "source_url": response.url,
                    }
                    data["quality_flags"] = missing_field_flags(
                        data,
                        ("major_id", "plan_count", "selection_requirement"),
                    )

                    item = validate_item(EnrollmentPlanItem, data)
                    if item:
                        yield item
                        await self.process_item(
                            item,
                            entity_type="enrollment_plans",
                            unique_keys={
                                "school_id": school_id,
                                "province_id": province_id,
                                "year": year,
                                "subject_category_id": subject_category_id,
                                "batch": batch,
                                "major_name": major_name,
                            },
                            upsert_fn=upsert_enrollment_plan,
                        )


def _column_index(header_map: dict[str, int] | None, candidates: tuple[str, ...], default: int) -> int:
    if header_map is None:
        return default
    for candidate in candidates:
        if candidate in header_map:
            return header_map[candidate]
    return default


def _cell_text(cells, index: int) -> str | None:
    if index < 0:
        return None
    if index >= len(cells):
        return None
    text = cells[index].css("::text").get("").strip()
    return text or None


async def _resolve_major_id(conn, major_name: str) -> int | None:
    rows = await find_majors_by_name(conn, major_name)
    if len(rows) == 1:
        return rows[0]["id"]
    return None
