from __future__ import annotations

import logging
from typing import Any, ClassVar

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.schools import upsert_school
from gaokao_vault.models.school import SchoolItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

MAX_SCH_ID = 5000


class SchoolSpider(BaseGaokaoSpider):
    name: str = "school_spider"
    task_type: str = TaskType.SCHOOLS

    async def start_requests(self):
        # Warmup: visit the list page first to establish Cookie/session state
        warmup_url = (
            f"{BASE_URL}/sch/search--ss-on,searchType-1,dataType-2,"
            "schName-,schProvince-,schAddress-,schType-,xlcc-,yxls-,"
            "dual-,naession-,f211-,f985-,autonomy-,central-,start-0.dhtml"
        )
        yield Request(warmup_url, callback=self.parse_warmup)

        for sch_id in range(1, MAX_SCH_ID + 1):
            url = f"{BASE_URL}/sch/schoolInfoMain--schId-{sch_id}.dhtml"
            yield Request(url, callback=self.parse, meta={"sch_id": sch_id})

    async def parse_warmup(self, response):
        """Handle warmup response — just log and return."""
        logger.info("Warmup request completed: status=%s url=%s", response.status, response.url)
        return
        yield  # make this an async generator to satisfy Request callback type

    async def parse(self, response: Response):
        if response.status == 404:
            return

        if response.request is None:
            return
        sch_id = response.request.meta.get("sch_id", 0)

        name = self._extract_school_name(response)
        if not name:
            logger.debug("No school name found for schId=%d", sch_id)
            return

        data: dict[str, Any] = {"sch_id": sch_id, "name": name}

        self._extract_detail_fields(response, data)
        self._extract_tags(response, data)
        self._extract_logo_and_intro(response, data)

        item = validate_item(SchoolItem, data)
        if item:
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
