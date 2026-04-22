from __future__ import annotations

import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlencode
from urllib.parse import urljoin

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import find_school_by_sch_id, upsert_school
from gaokao_vault.models.school import SchoolItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_SCH_ID = 5000
SEARCH_ENTRY_URL = f"{BASE_URL}/sch/search--ss-on,option-qg,searchType-1,start-0.dhtml"
_SCH_ID_PATTERN = re.compile(r"schoolInfo(?:Main)?--schId-(\d+)")
BRUTE_FORCE_PRIORITY = -10
PROVINCE_ENTRY_PRIORITY = 5
LIST_PAGE_PRIORITY = 10
PAGINATION_PRIORITY = 10


class SchoolSpider(BaseGaokaoSpider):
    name: str = "school_spider"
    task_type: str = TaskType.SCHOOLS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._province_map: dict[str, int] | None = None
        self._scheduled_school_candidates: dict[int, int | None] = {}
        self._refreshed_school_ids: set[int] = set()
        self._visited_list_urls: set[str] = set()

    async def _load_province_map(self) -> dict[str, int]:
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM provinces")
        return {row["name"]: row["id"] for row in rows}

    async def _resolve_province_id(self, province_text: str | None) -> int | None:
        if not province_text:
            return None

        if self._province_map is None:
            self._province_map = await self._load_province_map()

        normalized = (
            province_text.strip()
            .replace("壮族自治区", "")
            .replace("回族自治区", "")
            .replace("维吾尔自治区", "")
            .replace("自治区", "")
        )
        simplified = normalized.replace("省", "").replace("市", "")

        for name, province_id in self._province_map.items():
            plain_name = name.replace("省", "").replace("市", "")
            if name in normalized or plain_name in normalized or plain_name == simplified:
                return province_id

        return None

    def _schedule_school_detail(
        self,
        sch_id: int,
        candidate_province_id: int | None,
        *,
        priority: int = 0,
    ) -> Request | None:
        if sch_id not in self._scheduled_school_candidates:
            self._scheduled_school_candidates[sch_id] = candidate_province_id
            return Request(
                f"{BASE_URL}/sch/schoolInfoMain--schId-{sch_id}.dhtml",
                callback=self.parse,
                priority=priority,
                meta={"sch_id": sch_id, "candidate_province_id": candidate_province_id},
            )

        if (
            candidate_province_id is not None
            and self._scheduled_school_candidates[sch_id] is None
            and sch_id not in self._refreshed_school_ids
        ):
            self._scheduled_school_candidates[sch_id] = candidate_province_id
            self._refreshed_school_ids.add(sch_id)
            return Request(
                f"{BASE_URL}/sch/schoolInfoMain--schId-{sch_id}.dhtml",
                callback=self.parse,
                priority=priority,
                dont_filter=True,
                meta={"sch_id": sch_id, "candidate_province_id": candidate_province_id},
            )

        return None

    async def _preserve_existing_province_id(self, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("province_id") is not None:
            return item

        async with (await self._get_pool()).acquire() as conn:
            existing = await find_school_by_sch_id(conn, item["sch_id"])
        if existing and existing.get("province_id") is not None:
            item["province_id"] = existing["province_id"]
        return item

    @staticmethod
    def _warmup_url() -> str:
        return (
            f"{BASE_URL}/sch/search--ss-on,searchType-1,dataType-2,"
            "schName-,schProvince-,schAddress-,schType-,xlcc-,yxls-,"
            "dual-,naession-,f211-,f985-,autonomy-,central-,start-0.dhtml"
        )

    async def start_requests(self):
        # Warmup: visit the list page first to establish Cookie/session state
        yield Request(self._warmup_url(), callback=self.parse_warmup)
        yield Request(SEARCH_ENTRY_URL, callback=self.parse_search_entry)

        for sch_id in range(1, MAX_SCH_ID + 1):
            request = self._schedule_school_detail(sch_id, None, priority=BRUTE_FORCE_PRIORITY)
            if request is not None:
                yield request

    @staticmethod
    def _extract_sch_id_from_href(href: str) -> int | None:
        match = _SCH_ID_PATTERN.search(href)
        return int(match.group(1)) if match else None

    def _extract_next_page_urls(self, response: Response) -> list[str]:
        urls: list[str] = []
        for link in response.css("a[href*='searchType-1'][href*='start-']"):
            href = link.attrib.get("href", "").strip()
            if not href:
                continue

            link_text = "".join(part.strip() for part in link.css("::text").getall() if part.strip())
            if link_text not in {"下一页", "下页", ">", ">>"}:
                continue

            urls.append(urljoin(BASE_URL, href))

        return urls

    @staticmethod
    def _build_province_search_url(province_code: str) -> str:
        query = urlencode(
            {
                "searchType": "1",
                "ssdm": province_code,
                "yxls": "",
                "xlcc": "",
                "zgsx": "",
                "yxjbz": "",
            }
        )
        return f"{BASE_URL}/sch/search.do?{query}"

    async def parse_warmup(self, response):
        """Handle warmup response — just log and return."""
        logger.info("Warmup request completed: status=%s url=%s", response.status, response.url)
        return
        yield  # make this an async generator to satisfy Request callback type

    async def parse_search_entry(self, response: Response):
        for option in response.css("select[name='ssdm'] option"):
            province_code = option.attrib.get("value", "").strip()
            province_name = "".join(part.strip() for part in option.css("::text").getall() if part.strip())
            if not province_code or not province_name or province_name == "全部":
                continue

            try:
                candidate_province_id = await self._resolve_province_id(province_name)
            except Exception:
                logger.warning("Failed to resolve province for search entry '%s'", province_name, exc_info=True)
                candidate_province_id = None

            url = self._build_province_search_url(province_code)
            if url in self._visited_list_urls:
                continue

            self._visited_list_urls.add(url)
            yield Request(
                url,
                callback=self.parse_school_list,
                priority=PROVINCE_ENTRY_PRIORITY,
                meta={
                    "candidate_province_id": candidate_province_id,
                    "province_name": province_name,
                },
            )

    async def parse_school_list(self, response: Response):
        if response.request is None:
            return

        default_candidate_province_id = response.request.meta.get("candidate_province_id")

        for school_card in response.css("div.sch-item"):
            link = school_card.css("a.sch-department, .sch-title a.name, a[href*='schoolInfo--schId-']").first
            if not link:
                continue
            href = link.attrib.get("href", "").strip()
            sch_id = self._extract_sch_id_from_href(href)
            if sch_id is None:
                continue

            candidate_province_id = default_candidate_province_id
            department_link = school_card.css("a.sch-department").first
            if department_link:
                department_text = " ".join(
                    part.strip() for part in department_link.css("::text").getall() if part.strip()
                )
                if department_text:
                    try:
                        candidate_province_id = await self._resolve_province_id(department_text)
                    except Exception:
                        logger.warning(
                            "Failed to resolve province from school list card schId=%s text=%s",
                            sch_id,
                            department_text,
                            exc_info=True,
                        )

            request = self._schedule_school_detail(sch_id, candidate_province_id, priority=LIST_PAGE_PRIORITY)
            if request is not None:
                yield request

        for next_url in self._extract_next_page_urls(response):
            if next_url in self._visited_list_urls:
                continue

            self._visited_list_urls.add(next_url)
            yield Request(
                next_url,
                callback=self.parse_school_list,
                priority=PAGINATION_PRIORITY,
                meta=dict(response.request.meta),
            )

    async def parse(self, response: Response):
        if response.status == 404:
            return

        if response.request is None:
            return
        sch_id = response.request.meta.get("sch_id", 0)
        candidate_province_id = response.request.meta.get("candidate_province_id")

        name = self._extract_school_name(response)
        if not name:
            logger.debug("No school name found for schId=%d", sch_id)
            return

        data: dict[str, Any] = {"sch_id": sch_id, "name": name}

        self._extract_detail_fields(response, data)
        self._extract_tags(response, data)
        self._extract_logo_and_intro(response, data)
        try:
            detail_province_id = await self._resolve_province_id(data.get("city"))
        except Exception:
            logger.warning("Failed to resolve province for schId=%s", sch_id, exc_info=True)
            detail_province_id = None
        data["province_id"] = detail_province_id or candidate_province_id

        item = validate_item(SchoolItem, data)
        if item:
            item = await self._preserve_existing_province_id(item)
            yield item
            await self.process_item(
                item,
                entity_type="schools",
                unique_keys={"sch_id": sch_id},
                upsert_fn=upsert_school,
            )

    @staticmethod
    def _extract_school_name(response: Response) -> str:
        name_el = response.css("div.content-header")
        if not name_el:
            return ""
        for t in name_el.css("::text").getall():
            t = t.strip()
            if t and "关注" not in t and not t.isdigit():
                return t
        return ""

    @staticmethod
    def _extract_tags(response: Response, data: dict) -> None:
        tags_text = response.css("div.content-introduction span::text").getall()
        tag_set = {t.strip() for t in tags_text}
        data["is_211"] = "211" in tag_set
        data["is_985"] = "985" in tag_set
        data["is_double_first"] = any("双一流" in t for t in tag_set)
        data["is_private"] = "民办" in tag_set
        data["is_independent"] = "独立学院" in tag_set
        data["is_sino_foreign"] = "中外合作办学" in tag_set

    @staticmethod
    def _extract_logo_and_intro(response: Response, data: dict) -> None:
        logo_el = response.css("div.yxxx-header-img img::attr(src)")
        if logo_el:
            data["logo_url"] = logo_el.get("")

        intro_el = response.css("div.content-introduction")
        if intro_el:
            intro_text = intro_el.css("::text").getall()
            full_intro = " ".join(t.strip() for t in intro_text if t.strip())
            if full_intro:
                data["introduction"] = full_intro[:5000]

    _SPAN_FIELD_MAP: ClassVar[dict[str, str]] = {
        "yxszd": "city",
        "txdz": "address",
        "gfdh": "phone",
    }

    _LINK_FIELD_MAP: ClassVar[dict[str, str]] = {
        "gfwz": "website",
        "zswz": "recruit_website",
    }

    _TEXT_FIELD_MAP: ClassVar[dict[str, str]] = {
        "教育行政主管部门": "authority",
        "隶属于": "authority",
        "院校特性": "school_type",
        "院校类型": "school_type",
    }

    def _extract_detail_fields(self, response: Response, data: dict) -> None:
        """Extract fields from div.content-info-item using span classes and text labels."""
        department_texts = [
            text.strip()
            for text in response.css("div.content-introduction .department span::text").getall()
            if text.strip()
        ]
        if department_texts:
            data["authority"] = department_texts[-1]

        school_type_texts = [
            text.strip()
            for text in response.css("div.content-introduction .yxtx span::text").getall()
            if text.strip()
        ]
        if school_type_texts:
            data["school_type"] = " | ".join(school_type_texts)

        for css_cls, field in self._SPAN_FIELD_MAP.items():
            el = response.css(f"span.{css_cls}::text")
            if el:
                data[field] = el.get("").strip()

        for css_cls, field in self._LINK_FIELD_MAP.items():
            el = response.css(f"a.{css_cls}::attr(href)")
            if el:
                data[field] = el.get("").strip()

        for info_item in response.css("div.content-info-item"):
            full_text = " ".join(t.strip() for t in info_item.css("::text").getall())
            for label, field in self._TEXT_FIELD_MAP.items():
                if label in full_text:
                    self._extract_labeled_span(info_item, label, field, data)

    @staticmethod
    def _extract_labeled_span(info_item, label: str, field: str, data: dict) -> None:
        for s in info_item.css("span::text").getall():
            s = s.strip()
            if s and s != label:
                data[field] = s
                return
