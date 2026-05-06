from __future__ import annotations

import logging
import re
import string
from collections.abc import Iterable
from datetime import date, datetime
from html import unescape
from typing import ClassVar
from urllib.parse import urljoin

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import find_school_by_name
from gaokao_vault.db.queries.special import upsert_special_enrollment
from gaokao_vault.models.special import SpecialEnrollmentItem
from gaokao_vault.pipeline.quality import missing_field_flags
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.dxsbb import DXSBB_BASE_URL, iter_article_links, next_list_page_url, normalized_text

logger = logging.getLogger(__name__)

CHSI_STRONG_BASE_START_URL = "https://gaokao.chsi.com.cn/gkzt/jcxkzs"
CHSI_STRONG_BASE_SCHOOL_URL = "https://bm.chsi.com.cn/jcxkzs/sch/{school_code_raw}"
CHSI_STRONG_BASE_ANNOUNCEMENTS_URL = "https://bm.chsi.com.cn/jcxkzs/sch/ggtzs/{school_code_raw}"
CHSI_STRONG_BASE_LIST_PAGE_URL = "https://gaokao.chsi.com.cn/gkzt/jcxkzs#jcxkzs-sch"

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
DXSBB_SPECIAL_LISTS = [
    {
        "url": f"{DXSBB_BASE_URL}/news/list_130.html",
        "enrollment_type": "强基计划",
        "special_admission_type": "strong_foundation",
    },
    {
        "url": f"{DXSBB_BASE_URL}/news/list_976.html",
        "enrollment_type": "专项计划",
        "special_admission_type": "special_plan",
    },
]

CHSI_STRONG_BASE_SCHOOLS = (
    ("10001", "北京大学"),
    ("10002", "中国人民大学"),
    ("10003", "清华大学"),
    ("10006", "北京航空航天大学"),
    ("10007", "北京理工大学"),
    ("10019", "中国农业大学"),
    ("10027", "北京师范大学"),
    ("10052", "中央民族大学"),
    ("10055", "南开大学"),
    ("10056", "天津大学"),
    ("10141", "大连理工大学"),
    ("10145", "东北大学"),
    ("10183", "吉林大学"),
    ("10213", "哈尔滨工业大学"),
    ("10246", "复旦大学"),
    ("10247", "同济大学"),
    ("10248", "上海交通大学"),
    ("10269", "华东师范大学"),
    ("10284", "南京大学"),
    ("10286", "东南大学"),
    ("10335", "浙江大学"),
    ("10358", "中国科学技术大学"),
    ("10384", "厦门大学"),
    ("10422", "山东大学"),
    ("10423", "中国海洋大学"),
    ("10486", "武汉大学"),
    ("10487", "华中科技大学"),
    ("10532", "湖南大学"),
    ("10533", "中南大学"),
    ("10558", "中山大学"),
    ("10561", "华南理工大学"),
    ("10610", "四川大学"),
    ("10611", "重庆大学"),
    ("10614", "电子科技大学"),
    ("10698", "西安交通大学"),
    ("10699", "西北工业大学"),
    ("10712", "西北农林科技大学"),
    ("10730", "兰州大学"),
    ("92002", "国防科技大学"),
)


class SpecialSpider(BaseGaokaoSpider):
    """Crawl special enrollment types."""

    name: str = "special_spider"
    task_type: str = TaskType.SPECIAL
    allowed_domains: ClassVar[set[str]] = {
        "gaokao.chsi.com.cn",
        "bm.chsi.com.cn",
        "www.dxsbb.com",
        "dxsbb.com",
    }

    def configure_sessions(self, manager) -> None:
        manager.add("http", FetcherSession())

    async def start_requests(self):
        yield Request(
            CHSI_STRONG_BASE_START_URL,
            callback=self.parse_chsi_strong_base_index,
        )
        for source in DXSBB_SPECIAL_LISTS:
            yield Request(
                source["url"],
                callback=self.parse_dxsbb_list,
                meta={
                    "enrollment_type": source["enrollment_type"],
                    "special_admission_type": source["special_admission_type"],
                },
            )

    async def parse_chsi_strong_base_index(self, response: Response):
        if response.request is None or response.status == 404:
            return

        school_nodes = self._extract_chsi_strong_base_schools(response)
        for school_code_raw, school_name_raw in school_nodes:
            yield Request(
                CHSI_STRONG_BASE_SCHOOL_URL.format(school_code_raw=school_code_raw),
                callback=self.parse_chsi_strong_base_school,
                meta={
                    "school_code_raw": school_code_raw,
                    "school_name_raw": school_name_raw,
                    "application_url": CHSI_STRONG_BASE_SCHOOL_URL.format(school_code_raw=school_code_raw),
                },
            )

    async def parse_chsi_strong_base_school(self, response: Response):
        if response.request is None or response.status == 404:
            return

        school_code_raw = str(
            response.request.meta.get("school_code_raw") or self._extract_school_code_from_url(response.url) or ""
        )
        school_name_raw = str(
            response.request.meta.get("school_name_raw") or self._extract_school_name_from_page(response) or ""
        )
        application_url = str(response.request.meta.get("application_url") or response.url)
        vue_title = self._extract_vue_title(response)
        title = vue_title or (f"{school_name_raw}强基计划招生简章" if school_name_raw else "强基计划招生简章")
        content_html = self._extract_vue_content(response)
        publish_time = self._extract_vue_time(response)
        registration_start, registration_end = self._extract_time_window_from_text(publish_time or "")
        content_text = _normalized_html_text(content_html)
        eligible_majors = _extract_eligible_majors(content_text)

        if vue_title or content_html or content_text:
            data = _build_chsi_strong_base_data(
                title=title,
                content_html=content_html,
                content_text=content_text,
                source_url=application_url,
                source_section="charter",
                detail_url=application_url,
                application_url=application_url,
                school_code_raw=school_code_raw,
                school_name_raw=school_name_raw,
                publish_date=None,
                registration_start=registration_start,
                registration_end=registration_end,
                milestones=self._extract_milestones(publish_time),
                eligible_majors=eligible_majors,
            )
            item = validate_item(SpecialEnrollmentItem, data)
            if item:
                yield item
                await self._process_special_item(item)

        yield Request(
            CHSI_STRONG_BASE_ANNOUNCEMENTS_URL.format(school_code_raw=school_code_raw),
            callback=self.parse_chsi_strong_base_announcements,
            meta=_clean_meta({
                "school_code_raw": school_code_raw,
                "school_name_raw": school_name_raw,
                "application_url": application_url,
            }),
        )

    async def parse_chsi_strong_base_announcements(self, response: Response):
        if response.request is None or response.status == 404:
            return

        school_code_raw = str(
            response.request.meta.get("school_code_raw") or self._extract_school_code_from_url(response.url) or ""
        )
        school_name_raw = str(response.request.meta.get("school_name_raw") or "")
        application_url = str(
            response.request.meta.get("application_url")
            or CHSI_STRONG_BASE_SCHOOL_URL.format(school_code_raw=school_code_raw)
        )

        for link in self._iter_chsi_notice_links(response):
            yield Request(
                link["url"],
                callback=self.parse_chsi_strong_base_announcement_detail,
                meta=_clean_meta({
                    "title": link["title"],
                    "school_code_raw": school_code_raw,
                    "school_name_raw": school_name_raw,
                    "application_url": application_url,
                }),
            )

    async def parse_chsi_strong_base_announcement_detail(self, response: Response):
        if response.request is None or response.status == 404:
            return

        school_code_raw = str(
            response.request.meta.get("school_code_raw") or self._extract_school_code_from_url(response.url) or ""
        )
        school_name_raw = str(response.request.meta.get("school_name_raw") or "")
        application_url = str(
            response.request.meta.get("application_url")
            or CHSI_STRONG_BASE_SCHOOL_URL.format(school_code_raw=school_code_raw)
        )
        title = str(response.request.meta.get("title") or _first_text(response, "#article h1::text") or "").strip()
        publish_date = _parse_dxsbb_publish_date(_first_text(response, "#article .update::text") or "")
        content_el = response.css("#article .content, .article-content, .content")
        content_html = ""
        content_text = ""
        if content_el:
            content_html = content_el.get("").strip()[:10000]
            content_text = normalized_text(content_el[0])[:10000]

        strong_base_fields = _extract_strong_base_fields(content_text)
        registration_start = strong_base_fields.get("registration_start")
        registration_end = strong_base_fields.get("registration_end")
        eligible_majors = strong_base_fields.get("eligible_majors")
        data = _build_chsi_strong_base_data(
            title=title,
            content_html=content_html,
            content_text=content_text,
            source_url=response.url,
            source_section="announcement",
            detail_url=response.url,
            application_url=application_url,
            school_code_raw=school_code_raw,
            school_name_raw=school_name_raw,
            publish_date=publish_date,
            registration_start=registration_start if isinstance(registration_start, date) else None,
            registration_end=registration_end if isinstance(registration_end, date) else None,
            milestones={},
            eligible_majors=eligible_majors if isinstance(eligible_majors, list) else [],
        )
        item = validate_item(SpecialEnrollmentItem, data)
        if item:
            yield item
            await self._process_special_item(item)

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
                    await self._process_special_item(item)

        if items_found and current_page < MAX_PAGES:
            next_page = current_page + 1
            url = f"{BASE_URL}/gkxx/tsbm/?type={etype}&page={next_page}"
            yield Request(
                url,
                callback=self.parse,
                meta={"enrollment_type": etype, "page": next_page},
            )

    async def parse_dxsbb_list(self, response: Response):
        if response.request is None or response.status == 404:
            return

        enrollment_type = response.request.meta.get("enrollment_type")
        special_admission_type = response.request.meta.get("special_admission_type")
        for article in iter_article_links(
            response,
            predicate=lambda title: _special_title_matches(title, str(enrollment_type or "")),
        ):
            yield Request(
                article.url,
                callback=self.parse_dxsbb_article,
                meta={
                    "enrollment_type": _infer_enrollment_type(article.title, str(enrollment_type or "")),
                    "special_admission_type": _infer_special_admission_type(
                        article.title,
                        str(special_admission_type or ""),
                    ),
                    "title": article.title,
                },
            )

        next_url = next_list_page_url(response)
        if next_url:
            yield Request(
                next_url,
                callback=self.parse_dxsbb_list,
                meta={
                    "enrollment_type": enrollment_type,
                    "special_admission_type": special_admission_type,
                },
            )

    async def parse_dxsbb_article(self, response: Response):
        if response.request is None or response.status == 404:
            return

        data = dict(response.request.meta)
        title = str(data.get("title") or _first_text(response, "#article h1::text") or "").strip()
        publish_date = _parse_dxsbb_publish_date(_first_text(response, "#article .update::text") or "")
        content_el = response.css("#article .content")
        content_text = ""
        if content_el:
            data["content"] = content_el.get("").strip()[:10000]
            content_text = normalized_text(content_el[0])[:10000]
            data["content_text"] = content_text

        data["title"] = title
        data["year"] = _extract_year(title) or (publish_date.year if publish_date else datetime.now().year)
        data["publish_date"] = publish_date
        data["source_url"] = response.url

        if data.get("enrollment_type") == "强基计划":
            data.update(_extract_strong_base_fields(content_text))

        data["quality_flags"] = missing_field_flags(
            data,
            ("application_url", "registration_window", "eligible_majors"),
        )

        item = validate_item(SpecialEnrollmentItem, data)
        if item:
            yield item
            await self._process_special_item(item)

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
            content_text = normalized_text(content_el[0])[:10000]
            data["content_text"] = content_text

        if data.get("enrollment_type") == "强基计划":
            data.update(_extract_strong_base_fields(content_text))

        data["quality_flags"] = missing_field_flags(
            data,
            ("application_url", "registration_window", "eligible_majors"),
        )

        item = validate_item(SpecialEnrollmentItem, data)
        if item:
            yield item
            await self._process_special_item(item)

    async def _process_special_item(self, item: dict) -> None:
        await self.process_item(
            item,
            entity_type="special_enrollments",
            unique_keys={
                "enrollment_type": item.get("enrollment_type"),
                "school_id": item.get("school_id"),
                "year": item.get("year"),
                "title": item.get("title", ""),
            },
            upsert_fn=upsert_special_enrollment,
        )

    def _extract_chsi_strong_base_schools(self, response: Response) -> list[tuple[str, str]]:
        text = _response_text(response)
        if "jcxkzs-sch" in text or "强基计划" in text:
            matches = re.findall(r"/jcxkzs/sch/(\d{5}).*?(?:title|alt|aria-label)?=?\"?([^\"<>]{2,30})", text)
            parsed = [(code, name.strip()) for code, name in matches if code and name.strip()]
            if parsed:
                return parsed
        return list(CHSI_STRONG_BASE_SCHOOLS)

    def _extract_school_name_from_page(self, response: Response) -> str | None:
        title = _first_text(response, "title::text")
        if not title:
            return None
        match = re.match(r"(?P<school>.+?)(?:\d{4}年)?强基计划报名平台", title)
        if match is None:
            return None
        return match.group("school").strip() or None

    def _extract_vue_title(self, response: Response) -> str | None:
        value = _extract_vue_string(response, "jzbt")
        return value.strip() if value else None

    def _extract_vue_content(self, response: Response) -> str:
        return _extract_vue_string(response, "content") or ""

    def _extract_vue_time(self, response: Response) -> str | None:
        return _extract_vue_string(response, "time")

    def _extract_time_window_from_text(self, text: str) -> tuple[date | None, date | None]:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2}).*?(\d{4})-(\d{2})-(\d{2})", text)
        if match is None:
            return None, None
        try:
            return (
                date(int(match.group(1)), int(match.group(2)), int(match.group(3))),
                date(int(match.group(4)), int(match.group(5)), int(match.group(6))),
            )
        except ValueError:
            return None, None

    def _extract_milestones(self, text: str | None) -> dict[str, str | None]:
        if not text:
            return {}
        start, end = self._extract_time_window_from_text(text)
        if start is None and end is None:
            return {}
        return {
            "registration_start": start.isoformat() if start else None,
            "registration_end": end.isoformat() if end else None,
        }

    def _extract_school_code_from_url(self, url: str) -> str | None:
        match = re.search(r"/sch/(\d{5})", url)
        if match is None:
            return None
        return match.group(1)

    def _iter_chsi_notice_links(self, response: Response) -> Iterable[dict[str, str]]:
        seen: set[str] = set()
        for link in response.css("a"):
            href = link.attrib.get("href", "")
            title = link.css("::text").get("").strip()
            if not href or not title or "download" in href:
                continue
            url = _absolute_url(response.url, href)
            if url in seen:
                continue
            seen.add(url)
            yield {"url": url, "title": title}


def _normalized_html_text(html_text: str) -> str:
    if not html_text:
        return ""
    parts = []
    for paragraph in re.split(r"</p>|<br\s*/?>", html_text, flags=re.I):
        cleaned = unescape(re.sub(r"<[^>]+>", "", paragraph))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            parts.append(cleaned)
    return "\n".join(parts)


def _response_text(response: Response) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="ignore")
    if isinstance(body, str):
        return body
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="ignore")
    if isinstance(content, str):
        return content
    html = getattr(response, "html", None)
    return html if isinstance(html, str) else ""


def _extract_vue_string(response: Response, key: str) -> str | None:
    text = _response_text(response)
    if not text:
        text = "\n".join(part for part in response.css("script::text").getall() if part)
    match = re.search(rf"{re.escape(key)}\s*:\s*['\"](?P<value>(?:\\.|(?!['\"]).)*)['\"]", text, re.S)
    if match is None:
        return None
    return _decode_js_string(match.group("value"))


def _decode_js_string(value: str) -> str:
    if "\\" not in value:
        return value
    decoded: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            decoded.append(char)
            index += 1
            continue

        next_index = index + 1
        if next_index >= len(value):
            return value

        escaped = value[next_index]
        if escaped == "u":
            hex_digits = value[index + 2 : index + 6]
            if len(hex_digits) != 4 or not all(digit in string.hexdigits for digit in hex_digits):
                return value
            decoded.append(chr(int(hex_digits, 16)))
            index += 6
            continue

        simple_escapes = {
            '"': '"',
            "'": "'",
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        replacement = simple_escapes.get(escaped)
        if replacement is None:
            return value
        decoded.append(replacement)
        index += 2
    return "".join(decoded)


def _clean_meta(meta: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in meta.items() if value}


def _absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def _build_chsi_strong_base_data(
    *,
    title: str,
    content_html: str,
    content_text: str,
    source_url: str,
    source_section: str,
    detail_url: str,
    application_url: str,
    school_code_raw: str,
    school_name_raw: str,
    publish_date: date | None,
    registration_start: date | None,
    registration_end: date | None,
    milestones: dict[str, str | None],
    eligible_majors: list[str],
) -> dict:
    shortlist_rule = _extract_labeled_sentence(content_text, "入围规则")
    school_assessment = _extract_labeled_sentence(content_text, "校测规则") or _extract_labeled_sentence(
        content_text,
        "学校考核",
    )
    registration_window = _registration_window(registration_start, registration_end)
    data = {
        "enrollment_type": "强基计划",
        "special_admission_type": "strong_foundation",
        "province_code": None,
        "school_code_raw": school_code_raw or None,
        "school_name_raw": school_name_raw or None,
        "school_id": None,
        "year": _extract_year(title) or datetime.now().year,
        "title": title,
        "content": content_html,
        "content_text": content_text,
        "publish_date": publish_date,
        "source_url": source_url,
        "source_section": source_section,
        "detail_url": detail_url,
        "application_url": application_url,
        "registration_window": registration_window,
        "registration_start": registration_start,
        "registration_end": registration_end,
        "milestones": milestones,
        "shortlist_rule": shortlist_rule,
        "selection_rule": shortlist_rule,
        "school_assessment": school_assessment,
        "school_exam_rule": school_assessment,
        "composite_score_formula": _extract_labeled_sentence(content_text, "综合成绩公式")
        or _extract_labeled_sentence(content_text, "综合成绩"),
        "admission_rule": _extract_labeled_sentence(content_text, "录取规则"),
        "eligible_majors": eligible_majors,
    }
    data["quality_flags"] = missing_field_flags(
        data,
        ("application_url", "registration_window", "eligible_majors"),
    )
    return data


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dxsbb_publish_date(text: str) -> date | None:
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", text)
    if match is None:
        return None
    return _parse_date(match.group(1))


def _extract_year(text: str) -> int | None:
    match = re.search(r"(20\d{2})", text)
    if match is None:
        return None
    return int(match.group(1))


def _first_text(response: Response, selector: str) -> str | None:
    value = response.css(selector).get()
    return value.strip() if value else None


def _special_title_matches(title: str, enrollment_type: str) -> bool:
    if enrollment_type == "强基计划":
        return "强基" in title
    if enrollment_type == "专项计划":
        return "专项" in title
    return enrollment_type in title


def _infer_enrollment_type(title: str, default: str) -> str:
    if "强基" in title:
        return "强基计划"
    if "高校专项" in title:
        return "高校专项计划"
    if "国家专项" in title:
        return "国家专项计划"
    if "地方专项" in title:
        return "地方专项计划"
    return default


def _infer_special_admission_type(title: str, default: str) -> str | None:
    if "强基" in title:
        return "strong_foundation"
    if "专项" in title:
        return "special_plan"
    return default or None


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
    try:
        start = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        end = date(int(match.group(4)), int(match.group(5)), int(match.group(6)))
    except ValueError:
        return None, None
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
