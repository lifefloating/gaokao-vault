from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response

from gaokao_vault.constants import TaskType
from gaokao_vault.db.queries.admission import upsert_major_admission_result
from gaokao_vault.db.queries.majors import find_school_major_id_by_name
from gaokao_vault.models.admission import MajorAdmissionResultItem
from gaokao_vault.pipeline.batch_normalizer import normalize_batch
from gaokao_vault.pipeline.quality import missing_field_flags
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

DXSBB_BASE_URL = "https://www.dxsbb.com"
DXSBB_ADMISSION_LIST_URL = f"{DXSBB_BASE_URL}/news/list_458.html"
_DATA_SOURCE = "dxsbb.com"
_OFFICIAL_DATA_SOURCE = "gaokao.chsi.com.cn"
_ADMISSION_TITLE_PATTERN = re.compile(r"录取分数线")


class DxsbbAdmissionResultSpider(BaseGaokaoSpider):
    """Supplement major admission result rows from DXSBB static HTML tables."""

    name: str = "dxsbb_admission_result_spider"
    task_type: str = TaskType.DXSBB_ADMISSION_RESULTS
    allowed_domains = {"www.dxsbb.com", "dxsbb.com"}  # noqa: RUF012

    def configure_sessions(self, manager) -> None:
        manager.add("http", FetcherSession())

    async def start_requests(self):
        yield Request(DXSBB_ADMISSION_LIST_URL, callback=self.parse_list)

    async def parse_list(self, response: Response):
        if response.status == 404:
            return

        seen_urls: set[str] = set()
        for link in response.css(".listBox a[href^='/news/'], .listBox2news a[href^='/news/']"):
            href = link.attrib.get("href", "").strip()
            title = _link_title(link)
            if not href or not title or not _ADMISSION_TITLE_PATTERN.search(title):
                continue

            url = urljoin(DXSBB_BASE_URL, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            yield Request(url, callback=self.parse_article, meta={"title": title})

        for link in response.css(".listNav a[href*='list_458_']"):
            href = link.attrib.get("href", "").strip()
            if not href or "下一页" not in "".join(link.css("img::attr(alt), ::text").getall()):
                continue
            yield Request(urljoin(DXSBB_BASE_URL, href), callback=self.parse_list)

    async def parse_article(self, response: Response):
        if response.status == 404:
            return

        school_name = _extract_school_name(response)
        if not school_name:
            logger.debug("Skipping DXSBB article without school name url=%s", response.url)
            return

        async with (await self._get_pool()).acquire() as conn:
            school = await _find_school_by_name(conn, school_name)
            if school is None:
                logger.debug("Skipping DXSBB article with unknown school=%s url=%s", school_name, response.url)
                return

            provinces = await _load_province_map(conn)
            for table in response.css("#article .content table"):
                async for item in self._parse_score_table(conn, response.url, school, provinces, table):
                    yield item
                    await self._persist_item(item)

    async def _parse_score_table(
        self,
        conn: asyncpg.Connection,
        source_url: str,
        school: dict,
        provinces: dict[str, int],
        table,
    ):
        inferred_year = _infer_year_for_table(table)
        header_map: dict[str, int] | None = None
        for row in table.css("tr"):
            cells = row.css("th, td")
            texts = [_node_text(cell) for cell in cells]
            if not any(texts):
                continue

            if _looks_like_header(texts):
                header_map = {text: idx for idx, text in enumerate(texts) if text}
                continue

            if header_map is None:
                continue

            data = await self._build_item_data(conn, source_url, school, provinces, header_map, cells, inferred_year)
            if data is None or await _official_record_exists(conn, data):
                continue

            item = validate_item(MajorAdmissionResultItem, data)
            if item:
                yield item

    async def _persist_item(self, item: dict) -> None:
        await self.process_item(
            item,
            entity_type="major_admission_results",
            unique_keys={
                "school_id": item["school_id"],
                "major_id": item["major_id"],
                "province_id": item["province_id"],
                "year": item["year"],
                "subject_category_id": item.get("subject_category_id"),
                "batch": item["batch"],
            },
            upsert_fn=upsert_major_admission_result,
        )

    async def _build_item_data(
        self,
        conn: asyncpg.Connection,
        source_url: str,
        school: dict,
        provinces: dict[str, int],
        header_map: dict[str, int],
        cells,
        inferred_year: int | None,
    ) -> dict | None:
        year = _parse_year(_cell_text(cells, _column_index(header_map, ("年份",)))) or inferred_year
        province_name = _cell_text(cells, _column_index(header_map, ("省份", "录取省份")))
        major_name = _cell_text(cells, _column_index(header_map, ("专业名称", "专业")))
        if year is None or not province_name or not major_name:
            return None

        province_id = provinces.get(_normalize_province_name(province_name))
        if province_id is None:
            return None

        major_id = await find_school_major_id_by_name(
            conn,
            school["id"],
            major_name,
            fallback_to_unique_major=True,
        )
        if major_id is None:
            return None

        subject_category_raw = _cell_text(cells, _column_index(header_map, ("科类", "选科", "类别")))
        subject_category_id = await self._resolve_subject_category(subject_category_raw)
        batch_raw = _cell_text(cells, _column_index(header_map, ("类别", "批次", "录取批次"))) or "普通类"
        batch_info = normalize_batch(batch_raw)
        selection_requirement = _cell_text(cells, _column_index(header_map, ("选考要求", "选科要求")))

        data = {
            "school_id": school["id"],
            "major_id": major_id,
            "province_id": province_id,
            "year": year,
            "subject_category_id": subject_category_id,
            "batch": batch_raw,
            "batch_code": batch_info.code,
            "batch_category": batch_info.category,
            "batch_segment": batch_info.segment,
            "min_score": _parse_score(_cell_text(cells, _column_index(header_map, ("最低分", "最低分数")))),
            "min_rank": None,
            "avg_score": _parse_score(_cell_text(cells, _column_index(header_map, ("平均分",)))),
            "avg_rank": None,
            "max_score": _parse_score(_cell_text(cells, _column_index(header_map, ("最高分",)))),
            "max_rank": None,
            "admitted_count": _parse_int(_cell_text(cells, _column_index(header_map, ("录取人数", "录取数")))),
            "plan_count": None,
            "school_code_raw": None,
            "school_name_raw": school["name"],
            "major_group_code": None,
            "major_code_raw": None,
            "campus": None,
            "program_type": None,
            "eligibility_requirements": None,
            "physical_exam_or_political_review": None,
            "political_review_requirement": None,
            "service_obligation": None,
            "major_name_raw": major_name,
            "subject_category_raw": subject_category_raw,
            "batch_raw": batch_raw,
            "remark": f"选考要求: {selection_requirement}" if selection_requirement else None,
            "source_url": source_url,
            "data_source": _DATA_SOURCE,
            "source_updated_at": None,
        }
        data["quality_flags"] = missing_field_flags(data, ("min_score", "min_rank", "admitted_count"))
        return data


def _link_title(link) -> str:
    return " ".join(part.strip() for part in link.css("h3::text, img::attr(alt), ::text").getall() if part.strip())


def _node_text(node) -> str:
    return "".join(part.strip() for part in node.css("::text").getall() if part.strip())


def _cell_text(cells, index: int) -> str:
    if index < 0 or index >= len(cells):
        return ""
    return _node_text(cells[index])


def _column_index(header_map: dict[str, int], names: tuple[str, ...]) -> int:
    for name in names:
        for header, index in header_map.items():
            if name in header:
                return index
    return -1


def _looks_like_header(texts: list[str]) -> bool:
    joined = "|".join(texts)
    return "专业" in joined and ("最低分" in joined or "最高分" in joined)


def _infer_year_for_table(table) -> int | None:
    previous = table.previous
    for _ in range(8):
        if previous is None:
            return None
        year = _parse_year(str(previous.get_all_text(separator="", strip=True)))
        if year is not None:
            return year
        previous = previous.previous
    return None


def _extract_school_name(response: Response) -> str | None:
    school = response.css(".position a[href^='/school/']::text").get()
    if school:
        return school.strip()

    title = response.css("#article h1::text, h1::text").get() or ""
    match = re.search(r"(?:20\d{2})?(.+?)录取分数线", title)
    return match.group(1).strip() if match else None


def _normalize_province_name(name: str) -> str:
    return (
        name
        .strip()
        .replace("省", "")
        .replace("市", "")
        .replace("壮族自治区", "")
        .replace("回族自治区", "")
        .replace("维吾尔自治区", "")
        .replace("自治区", "")
    )


def _parse_int(value: str) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _parse_year(value: str) -> int | None:
    match = re.search(r"20\d{2}", value)
    return int(match.group()) if match else None


def _parse_score(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(float(value.strip()))
    except ValueError:
        return _parse_int(value)


async def _find_school_by_name(conn: asyncpg.Connection, school_name: str) -> dict | None:
    row = await conn.fetchrow("SELECT id, name FROM schools WHERE name = $1", school_name)
    return dict(row) if row else None


async def _load_province_map(conn: asyncpg.Connection) -> dict[str, int]:
    rows = await conn.fetch("SELECT id, name FROM provinces")
    return {_normalize_province_name(row["name"]): row["id"] for row in rows}


async def _official_record_exists(conn: asyncpg.Connection, data: dict) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM major_admission_results
                WHERE school_id = $1
                  AND major_id = $2
                  AND province_id = $3
                  AND year = $4
                  AND subject_category_id IS NOT DISTINCT FROM $5
                  AND batch = $6
                  AND data_source = $7
            ) AS official_exists
            """,
            data["school_id"],
            data["major_id"],
            data["province_id"],
            data["year"],
            data.get("subject_category_id"),
            data["batch"],
            _OFFICIAL_DATA_SOURCE,
        )
    )
