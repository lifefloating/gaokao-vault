from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.enrollment import upsert_enrollment_plan
from gaokao_vault.db.queries.majors import find_majors_by_name
from gaokao_vault.models.enrollment import EnrollmentPlanItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

PROVINCE_IDS = list(range(1, 32))
YEAR_START = 2020
YEAR_END = datetime.now().year


class EnrollmentPlanSpider(BaseGaokaoSpider):
    """Crawl enrollment plans: school x province x year."""

    name: str = "enrollment_plan_spider"
    task_type: str = TaskType.ENROLLMENT_PLANS

    concurrent_requests = 3
    download_delay = 2.0

    async def start_requests(self):
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            for province_id in PROVINCE_IDS:
                for year in range(YEAR_START, YEAR_END + 1):
                    url = (
                        f"{BASE_URL}/sch/schoolInfo--schId-{sch_id}.dhtml?provinceId={province_id}&year={year}&tab=plan"
                    )
                    yield Request(
                        url,
                        callback=self.parse,
                        meta={
                            "school_id": school_id,
                            "province_id": province_id,
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
            header_map: dict[str, int] | None = None
            for row in response.css("table.plan-table tr"):
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

                if not major_name:
                    continue

                major_id = await _resolve_major_id(conn, major_name)
                subject_category_id = await self._resolve_subject_category(subject_category_raw or "")
                plan_count = int(plan_text) if plan_text and plan_text.isdigit() else None

                data = {
                    "school_id": school_id,
                    "province_id": province_id,
                    "year": year,
                    "subject_category_id": subject_category_id,
                    "batch": batch,
                    "major_name": major_name,
                    "major_id": major_id,
                    "plan_count": plan_count,
                    "duration": duration,
                    "tuition": tuition,
                    "note": note,
                }

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
    if index >= len(cells):
        return None
    text = cells[index].css("::text").get("").strip()
    return text or None


async def _resolve_major_id(conn, major_name: str) -> int | None:
    rows = await find_majors_by_name(conn, major_name)
    if len(rows) == 1:
        return rows[0]["id"]
    return None
