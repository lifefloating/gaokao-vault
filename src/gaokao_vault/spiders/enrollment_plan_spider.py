from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response

from gaokao_vault.constants import TaskType
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
from gaokao_vault.spiders.response_utils import response_json
from gaokao_vault.spiders.scope import load_province_targets
from gaokao_vault.spiders.table_candidates import candidate_tables

logger = logging.getLogger(__name__)

YEAR_START = 2020
DATA_SOURCE = "gaokao.cn"
CHSI_DATA_SOURCE = "gaokao.chsi.com.cn"
GAOKAO_STATIC_BASE_URL = "https://static-data.gaokao.cn"
SCHOOL_NAME_INDEX_URL = f"{GAOKAO_STATIC_BASE_URL}/www/2.0/school/name.json"
PLAN_DICTIONARY_URL_TEMPLATE = f"{GAOKAO_STATIC_BASE_URL}/www/2.0/yk/school/{{school_id}}/dic/specialplan.json"
PLAN_URL_TEMPLATE = f"{GAOKAO_STATIC_BASE_URL}/www/2.0/schoolspecialplan/{{school_id}}/{{year}}/{{province}}.json"
_GAOKAO_TYPE_NAMES = {
    "1": "理科",
    "2": "文科",
    "3": "综合",
    "4": "艺术类",
    "5": "体育类",
    "2073": "物理类",
    "2074": "历史类",
    "2292": "艺术类(历史)",
    "2293": "艺术类(物理)",
    "2294": "体育类(历史)",
    "2295": "体育类(物理)",
}
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

    allowed_domains: ClassVar[set[str]] = {"static-data.gaokao.cn"}
    concurrent_requests = 8
    concurrent_requests_per_domain = 4
    download_delay = 0.2

    def configure_sessions(self, manager) -> None:
        manager.add(
            "http",
            FetcherSession(
                timeout=30,
                headers={
                    "Referer": "https://www.gaokao.cn/",
                    "Accept": "application/json,text/plain,*/*",
                },
            ),
        )

    async def start_requests(self):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id, name FROM schools ORDER BY id")

        provinces = await load_province_targets(pool)
        years = _select_plan_years(self.mode, datetime.now())
        schools = [{"id": int(row["id"]), "sch_id": int(row["sch_id"]), "name": str(row["name"])} for row in rows]
        province_meta = [
            {"id": province.id, "name": province.name, "code": province.url_value} for province in provinces
        ]

        yield Request(
            SCHOOL_NAME_INDEX_URL,
            callback=self.parse_school_name_index,
            meta={"schools": schools, "provinces": province_meta, "years": years},
        )

    async def parse_school_name_index(self, response: Response):
        if response.status == 404 or response.request is None:
            return

        result = response_json(response)
        if result is None or result.get("code") != "0000":
            logger.debug("Invalid gaokao school name index url=%s", response.url)
            return

        school_index = _build_gaokao_school_index(result.get("data"))
        provinces = response.request.meta.get("provinces") or []
        years = response.request.meta.get("years") or []
        for school in response.request.meta.get("schools") or []:
            school_name = _safe_text(school.get("name"))
            gaokao_school_id = school_index.get(_normalize_school_name(school_name or ""))
            if not gaokao_school_id:
                logger.debug("Skipping enrollment plan for unmatched school=%s", school_name)
                continue

            yield Request(
                PLAN_DICTIONARY_URL_TEMPLATE.format(school_id=gaokao_school_id),
                callback=self.parse_plan_dictionary,
                meta={
                    "school_id": school["id"],
                    "school_name": school_name,
                    "gaokao_school_id": gaokao_school_id,
                    "provinces": provinces,
                    "years": years,
                },
            )

    async def parse_plan_dictionary(self, response: Response):
        if response.status == 404 or response.request is None:
            return

        result = response_json(response)
        if result is None or result.get("code") != "0000":
            logger.debug("Invalid gaokao plan dictionary url=%s", response.url)
            return

        data = result.get("data")
        if not isinstance(data, dict):
            return

        available_years_by_province = data.get("year")
        if not isinstance(available_years_by_province, dict):
            return

        gaokao_school_id = response.request.meta.get("gaokao_school_id")
        allowed_years = _normalize_year_list(response.request.meta.get("years") or [])

        for province in response.request.meta.get("provinces") or []:
            province_code = str(province.get("code") or "").strip()
            available_years = {_safe_int(year) for year in available_years_by_province.get(province_code, [])}
            missing_years = sorted(set(allowed_years) - available_years)
            if missing_years:
                logger.debug(
                    "Enrollment plan dictionary missing years for school=%s province=%s available=%s missing=%s",
                    response.request.meta.get("school_name"),
                    province_code,
                    sorted(year for year in available_years if year is not None),
                    missing_years,
                )
            for year in allowed_years:
                yield Request(
                    PLAN_URL_TEMPLATE.format(school_id=gaokao_school_id, year=year, province=province_code),
                    callback=self.parse,
                    meta={
                        "school_id": response.request.meta.get("school_id"),
                        "school_name": response.request.meta.get("school_name"),
                        "gaokao_school_id": gaokao_school_id,
                        "province_id": province.get("id"),
                        "province_code": province_code,
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

        result = response_json(response)
        if result is not None:
            async for item in self._parse_static_plan_json(response, result):
                yield item
            return

        async for item in self._parse_html_plan(response):
            yield item

    async def _parse_html_plan(self, response: Response):
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

                    data = await self._build_html_plan_item(conn, response, header_map, cells)
                    if data is None:
                        continue
                    item = validate_item(EnrollmentPlanItem, data)
                    if item:
                        yield item
                        await self._persist_item(item)

    async def _build_html_plan_item(self, conn, response: Response, header_map: dict[str, int] | None, cells):
        if response.request is None:
            return None

        major_name = _cell_text(cells, _column_index(header_map, ("专业名称", "专业"), 0))
        if not major_name:
            return None

        subject_category_raw = _cell_text(cells, _column_index(header_map, ("科类", "选科"), 1))
        batch = _cell_text(cells, _column_index(header_map, ("批次",), 2))
        plan_text = _cell_text(cells, _column_index(header_map, ("计划数",), 3))
        duration = _cell_text(cells, _column_index(header_map, ("学制",), 4))
        tuition = _cell_text(cells, _column_index(header_map, ("学费",), 5))
        note = _cell_text(cells, _column_index(header_map, ("备注", "说明"), 6))
        major_group_code = _cell_text(cells, _column_index(header_map, ("院校专业组", "专业组", "专业组代码"), -1))
        major_code_raw = _cell_text(cells, _column_index(header_map, ("专业代码",), -1))
        selection_requirement = _cell_text(cells, _column_index(header_map, ("选科要求", "再选科目"), -1))
        campus = _cell_text(cells, _column_index(header_map, ("校区",), -1))
        education_location = _cell_text(cells, _column_index(header_map, ("办学地点", "就读地点"), -1))

        major_id = await _resolve_major_id(conn, major_name)
        subject_category_id = await self._resolve_subject_category(subject_category_raw or "")
        batch_info = normalize_batch(batch)
        data = {
            "school_id": response.request.meta.get("school_id"),
            "province_id": response.request.meta.get("province_id"),
            "year": response.request.meta.get("year"),
            "subject_category_id": subject_category_id,
            "batch": batch,
            "batch_code": batch_info.code,
            "batch_category": batch_info.category,
            "batch_segment": batch_info.segment,
            "major_name": major_name,
            "major_id": major_id,
            "plan_count": int(plan_text) if plan_text and plan_text.isdigit() else None,
            "duration": duration,
            "tuition": tuition,
            "note": note,
            "major_group_code": major_group_code,
            "major_code_raw": major_code_raw,
            "campus": campus,
            "education_location": education_location,
            "selection_requirement": selection_requirement,
            "physical_exam_limit": extract_physical_exam_limit(note),
            "single_subject_limit": extract_single_subject_limit(note),
            "adjustment_rule": extract_adjustment_rule(note),
            "program_type": extract_program_type(batch, note),
            "eligibility_requirements": extract_eligibility_requirements(note),
            "physical_exam_or_political_review": extract_physical_exam_or_political_review(note),
            "political_review_requirement": extract_political_review_requirement(note),
            "service_obligation": extract_service_obligation(note),
            "data_source": CHSI_DATA_SOURCE,
            "source_url": response.url,
        }
        data["quality_flags"] = missing_field_flags(data, ("major_id", "plan_count", "selection_requirement"))
        return data

    async def _parse_static_plan_json(self, response: Response, result: dict[str, Any]):
        if result.get("code") != "0000":
            return

        data = result.get("data")
        if not isinstance(data, dict):
            return

        async with (await self._get_pool()).acquire() as conn:
            for group in data.values():
                if not isinstance(group, dict):
                    continue
                records = group.get("item")
                if not isinstance(records, list):
                    continue
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    item_data = await self._build_static_plan_item(conn, response, record)
                    if item_data is None:
                        continue
                    item = validate_item(EnrollmentPlanItem, item_data)
                    if item:
                        yield item
                        await self._persist_item(item)

    async def _build_static_plan_item(self, conn, response: Response, record: dict[str, Any]) -> dict[str, Any] | None:
        if response.request is None:
            return None

        school_id = response.request.meta.get("school_id")
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")
        if not school_id or not province_id or not year:
            return None

        major_name = _first_text(record.get("spname"), record.get("sp_name"))
        if not major_name:
            return None

        major_lookup_name = _first_text(record.get("sp_name"), major_name)
        major_id = await _resolve_major_id(conn, major_lookup_name) if major_lookup_name else None
        subject_category_raw = _gaokao_subject_category(record)
        subject_category_id = await self._resolve_subject_category(subject_category_raw or "")
        batch = _first_text(record.get("local_batch_name"), record.get("batch"))
        batch_info = normalize_batch(batch)
        note = _join_note(record.get("remark"), record.get("info"))
        selection_requirement = _first_text(record.get("sg_info"), record.get("sp_info"), record.get("sp_xuanke"))

        item_data = {
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
            "plan_count": _safe_int(record.get("num")),
            "duration": _first_text(record.get("length")),
            "tuition": _first_text(record.get("tuition")),
            "note": note,
            "major_group_code": _first_text(record.get("sg_name"), record.get("special_group")),
            "major_code_raw": _first_text(record.get("spcode")),
            "campus": _first_text(record.get("campus"), record.get("school_area")),
            "education_location": _first_text(record.get("address"), record.get("place")),
            "selection_requirement": selection_requirement,
            "physical_exam_limit": extract_physical_exam_limit(note),
            "single_subject_limit": extract_single_subject_limit(note),
            "adjustment_rule": extract_adjustment_rule(note),
            "program_type": extract_program_type(batch, note, _first_text(record.get("zslx_name"))),
            "eligibility_requirements": extract_eligibility_requirements(note),
            "physical_exam_or_political_review": extract_physical_exam_or_political_review(note),
            "political_review_requirement": extract_political_review_requirement(note),
            "service_obligation": extract_service_obligation(note),
            "data_source": DATA_SOURCE,
            "source_url": response.url,
        }
        item_data["quality_flags"] = missing_field_flags(
            item_data,
            ("major_id", "plan_count", "selection_requirement"),
        )
        return item_data

    async def _persist_item(self, item: dict[str, Any]) -> None:
        await self.process_item(
            item,
            entity_type="enrollment_plans",
            unique_keys={
                "school_id": item["school_id"],
                "province_id": item["province_id"],
                "year": item["year"],
                "subject_category_id": item.get("subject_category_id"),
                "batch": item.get("batch"),
                "major_name": item.get("major_name"),
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


def _build_gaokao_school_index(rows: Any) -> dict[str, str]:
    if not isinstance(rows, list):
        return {}

    school_index: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        school_id = _first_text(row.get("school_id"))
        if not school_id:
            continue
        for name_key in ("name", "old_name"):
            name = _normalize_school_name(_first_text(row.get(name_key)) or "")
            if name and name not in school_index:
                school_index[name] = school_id
    return school_index


def _normalize_school_name(name: str) -> str:
    return "".join(name.split())


def _gaokao_subject_category(record: dict[str, Any]) -> str | None:
    type_code = _first_text(record.get("type"))
    if type_code and type_code in _GAOKAO_TYPE_NAMES:
        return _GAOKAO_TYPE_NAMES[type_code]
    return _first_text(record.get("local_type_name"), record.get("type"))


def _join_note(*values: Any) -> str | None:
    parts = [_safe_text(value) for value in values]
    text = "".join(part for part in parts if part)
    return text or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _safe_text(value)
        if text:
            return text
    return None


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _resolve_major_id(conn, major_name: str) -> int | None:
    rows = await find_majors_by_name(conn, major_name)
    if len(rows) == 1:
        return rows[0]["id"]
    return None


def _select_plan_years(mode: str, now: datetime) -> list[int]:
    if mode != "incremental":
        return list(range(YEAR_START, now.year + 1))

    if now.month == 12:
        candidates = [now.year, now.year - 1, now.year - 2]
    else:
        candidates = [now.year - 1, now.year - 2, now.year - 3]
    return [year for year in candidates if year >= YEAR_START]


def _normalize_year_list(years: list[int | str | None]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for year in years:
        value = _safe_int(year)
        if value is None or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized
