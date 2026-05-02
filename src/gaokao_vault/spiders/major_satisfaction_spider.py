from __future__ import annotations

import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import find_school_major_id_by_name, upsert_major_satisfaction
from gaokao_vault.models.major import MajorSatisfactionItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.response_utils import response_json

logger = logging.getLogger(__name__)

APPRAISAL_INFO_URL_TEMPLATE = f"{BASE_URL}/zyk/pub/appraisalinfo/{{sch_id}}"
SPEC_APPRAISAL_URL_TEMPLATE = f"{BASE_URL}/zyk/pub/myd/specAppraisalTopMore?schId={{sch_id}}&type=3&cc={{cc}}"


class MajorSatisfactionSpider(BaseGaokaoSpider):
    """Crawl major satisfaction scores from public satisfaction table pages."""

    name: str = "major_satisfaction_spider"
    task_type: str = TaskType.MAJOR_SATISFACTION

    async def start_requests(self):
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch("SELECT id, sch_id FROM schools ORDER BY id")

        for row in rows:
            school_id = row["id"]
            sch_id = row["sch_id"]
            url = APPRAISAL_INFO_URL_TEMPLATE.format(sch_id=sch_id)
            yield Request(
                url,
                callback=self.parse_appraisal_info,
                meta={"school_id": school_id, "sch_id": sch_id},
            )

    async def parse_appraisal_info(self, response: Response):
        if response.status == 404 or response.request is None:
            return

        school_id = response.request.meta.get("school_id")
        if not school_id:
            return

        result = response_json(response)
        if result is None:
            logger.debug("Invalid appraisal JSON school_id=%s url=%s", school_id, response.url)
            return

        msg = result.get("msg")
        if not isinstance(msg, dict):
            return

        appraisal_sch_id = _safe_str(msg.get("schDicId"))
        if not appraisal_sch_id:
            logger.debug("No schDicId in appraisal JSON school_id=%s url=%s", school_id, response.url)
            return

        for cc, education_level in (("1", "本科"), ("2", "专科")):
            yield Request(
                SPEC_APPRAISAL_URL_TEMPLATE.format(sch_id=appraisal_sch_id, cc=cc),
                callback=self.parse_satisfaction_table,
                meta={
                    "school_id": school_id,
                    "appraisal_sch_id": appraisal_sch_id,
                    "education_level": education_level,
                },
            )

    async def parse_satisfaction_table(self, response: Response):
        if response.status == 404 or response.request is None:
            return

        school_id = response.request.meta.get("school_id")
        education_level = response.request.meta.get("education_level")
        if not school_id or not education_level:
            return

        async with (await self._get_pool()).acquire() as conn:
            for row in response.css("table.myd-detail-table tbody tr"):
                cells = row.css("td")
                if len(cells) < 2:
                    continue

                major_name = "".join(part.strip() for part in cells[0].css("::text").getall() if part.strip())
                if not major_name:
                    continue

                major_id = await find_school_major_id_by_name(
                    conn,
                    school_id,
                    major_name,
                    education_level=education_level,
                )
                if major_id is None:
                    logger.debug(
                        "Skipping unmatched satisfaction row school_id=%s education_level=%s major_name=%s url=%s",
                        school_id,
                        education_level,
                        major_name,
                        response.url,
                    )
                    continue

                data = {
                    "major_id": major_id,
                    "school_id": school_id,
                    "overall_score": _safe_float(_hidden_value(cells[1])),
                    "vote_count": None,
                }

                item = validate_item(MajorSatisfactionItem, data)
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="major_satisfaction",
                        unique_keys={"major_id": major_id, "school_id": school_id},
                        upsert_fn=upsert_major_satisfaction,
                    )


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_str(val) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _hidden_value(cell) -> str | None:
    value = cell.css("input[type=hidden]::attr(value)").get()
    return value.strip() if value else None
