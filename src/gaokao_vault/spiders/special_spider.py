from __future__ import annotations

import logging
import re
from datetime import date, datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import find_school_by_name
from gaokao_vault.db.queries.special import upsert_special_enrollment
from gaokao_vault.models.special import SpecialEnrollmentItem
from gaokao_vault.pipeline.quality import missing_field_flags
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

ENROLLMENT_TYPES = [
    "自主招生",
    "高校专项计划",
    "国家专项计划",
    "地方专项计划",
    "保送生",
    "艺术类",
    "体育类",
    "强基计划",
    "综合评价",
]

MAX_PAGES = 20


class SpecialSpider(BaseGaokaoSpider):
    """Crawl special enrollment types."""

    name: str = "special_spider"
    task_type: str = TaskType.SPECIAL

    async def start_requests(self):
        for etype in ENROLLMENT_TYPES:
            url = f"{BASE_URL}/gkxx/tsbm/?type={etype}&page=1"
            yield Request(
                url,
                callback=self.parse,
                meta={"enrollment_type": etype, "page": 1},
            )

    async def parse(self, response: Response):
        if response.request is None:
            return
        etype = response.request.meta.get("enrollment_type")
        current_page = response.request.meta.get("page", 1)
        items_found = False

        for item_el in response.css("ul.news-list li"):
            items_found = True

            link = item_el.css("a")
            if not link:
                continue

            title = link.css("::text").get("").strip()
            href = link[0].attrib.get("href", "")
            date_text = item_el.css("span.date::text").get("").strip()
            year_text = item_el.css("span.year::text").get("").strip()

            if not title:
                continue

            publish_date = _parse_date(date_text)
            year = (
                int(year_text) if year_text.isdigit() else (publish_date.year if publish_date else datetime.now().year)
            )
            source_url = response.urljoin(href) if href else None

            data = {
                "enrollment_type": etype,
                "year": year,
                "title": title,
                "publish_date": publish_date,
                "source_url": source_url,
            }

            if href:
                yield Request(
                    response.urljoin(href),
                    callback=self.parse_detail,
                    meta={"item_data": data},
                )
            else:
                item = validate_item(SpecialEnrollmentItem, data)
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="special_enrollments",
                        unique_keys={
                            "enrollment_type": etype,
                            "school_id": None,
                            "year": year,
                            "title": title,
                        },
                        upsert_fn=upsert_special_enrollment,
                    )

        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/gkxx/tsbm/?type={etype}&page={next_page}"
            yield Request(
                url,
                callback=self.parse,
                meta={"enrollment_type": etype, "page": next_page},
            )

    async def parse_detail(self, response: Response):
        if response.request is None:
            return
        data = response.request.meta.get("item_data", {})
        if data.get("school_id") is None:
            school_name = _extract_school_name_from_title(str(data.get("title") or ""))
            if school_name:
                pool = await self._get_pool()
                async with pool.acquire() as conn:
                    school = await find_school_by_name(conn, school_name)
                if school:
                    data["school_id"] = school["id"]

        content_el = response.css("div.article-content")
        content_text = ""
        if content_el:
            data["content"] = content_el.get("").strip()[:10000]
            content_text = "\n".join(part.strip() for part in content_el.css("::text").getall() if part.strip())

        if data.get("enrollment_type") == "强基计划":
            data.update(_extract_strong_base_fields(content_text))

        data["quality_flags"] = missing_field_flags(
            data,
            ("application_url", "registration_window", "eligible_majors"),
        )

        item = validate_item(SpecialEnrollmentItem, data)
        if item:
            yield item
            await self.process_item(
                item,
                entity_type="special_enrollments",
                unique_keys={
                    "enrollment_type": data.get("enrollment_type"),
                    "school_id": data.get("school_id"),
                    "year": data.get("year"),
                    "title": data.get("title", ""),
                },
                upsert_fn=upsert_special_enrollment,
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


def _extract_school_name_from_title(title: str) -> str | None:
    match = re.match(
        r"(?P<school>.+?)(?:\d{4}年)?(?:强基计划|高校专项计划|综合评价|保送生|招生简章|招生章程)",
        title,
    )
    if match is None:
        return None
    value = match.group("school").strip()
    return value or None


def _extract_strong_base_fields(text: str) -> dict:
    registration_start, registration_end = _extract_registration_dates(text)
    shortlist_rule = _extract_labeled_sentence(text, "入围规则")
    school_assessment = _extract_labeled_sentence(text, "校测规则") or _extract_labeled_sentence(text, "学校考核")
    return {
        "special_admission_type": "strong_foundation",
        "application_url": _extract_application_url(text),
        "registration_window": _registration_window(registration_start, registration_end),
        "registration_start": registration_start,
        "registration_end": registration_end,
        "shortlist_rule": shortlist_rule,
        "selection_rule": shortlist_rule,
        "school_assessment": school_assessment,
        "school_exam_rule": school_assessment,
        "composite_score_formula": _extract_labeled_sentence(text, "综合成绩公式")
        or _extract_labeled_sentence(text, "综合成绩"),
        "admission_rule": _extract_labeled_sentence(text, "录取规则"),
        "eligible_majors": _extract_eligible_majors(text),
    }


def _extract_application_url(text: str) -> str | None:
    match = re.search(r"https://bm\.chsi\.com\.cn/[^\s<]+", text)
    if match is None:
        return None
    return match.group(0).rstrip(".")


def _extract_registration_dates(text: str) -> tuple[date | None, date | None]:
    match = re.search(
        r"报名时间\s*[:\uFF1A]\s*(\d{4})年(\d{1,2})月(\d{1,2})日?\s*至\s*(\d{4})年(\d{1,2})月(\d{1,2})日?",
        text,
    )
    if match is None:
        return None, None
    start = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    end = date(int(match.group(4)), int(match.group(5)), int(match.group(6)))
    return start, end


def _registration_window(registration_start: date | None, registration_end: date | None) -> dict[str, str | None]:
    if registration_start is None and registration_end is None:
        return {}
    return {
        "start": registration_start.isoformat() if registration_start else None,
        "end": registration_end.isoformat() if registration_end else None,
    }


def _extract_labeled_sentence(text: str, label: str) -> str | None:
    match = re.search(rf"{label}\s*[:\uFF1A]\s*([^\n\u3002.]+)", text)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _extract_eligible_majors(text: str) -> list[str]:
    match = re.search(r"招生专业\s*[:\uFF1A]\s*([^\n\u3002.]+)", text)
    if match is None:
        return []
    return [part.strip() for part in re.split(r"[\u3001,\uFF0C;\uFF1B]", match.group(1)) if part.strip()]
