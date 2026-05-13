from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response

from gaokao_vault.constants import TaskType
from gaokao_vault.db.queries.admission import upsert_major_admission_result
from gaokao_vault.db.queries.majors import find_school_major_id_by_name
from gaokao_vault.db.queries.scores import find_score_segment_rank
from gaokao_vault.models.admission import MajorAdmissionResultItem
from gaokao_vault.pipeline.batch_normalizer import normalize_batch
from gaokao_vault.pipeline.quality import missing_field_flags
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.dxsbb import DXSBB_BASE_URL, iter_article_links, next_list_page_url

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

DXSBB_ADMISSION_LIST_URL = f"{DXSBB_BASE_URL}/news/list_458.html"
_DATA_SOURCE = "dxsbb.com"
_OFFICIAL_DATA_SOURCE = "gaokao.chsi.com.cn"
_ADMISSION_TITLE_PATTERN = re.compile(r"录取分数线")


class DxsbbAdmissionResultSpider(BaseGaokaoSpider):
    """Supplement major admission result rows from DXSBB static HTML tables."""

    name: str = "dxsbb_admission_result_spider"
    task_type: str = TaskType.DXSBB_ADMISSION_RESULTS
    allowed_domains = {"www.dxsbb.com", "dxsbb.com"}  # noqa: RUF012

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._score_rank_cache: dict[tuple[int, int, int | None, int], int | None] = {}

    def configure_sessions(self, manager) -> None:
        manager.add("http", FetcherSession())

    async def start_requests(self):
        yield Request(DXSBB_ADMISSION_LIST_URL, callback=self.parse_list)

    async def parse_list(self, response: Response):
        if response.status == 404:
            return

        for article in iter_article_links(
            response, predicate=lambda title: bool(_ADMISSION_TITLE_PATTERN.search(title))
        ):
            yield Request(article.url, callback=self.parse_article, meta={"title": article.title})

        next_url = next_list_page_url(response)
        if next_url and "list_458_" in next_url:
            yield Request(next_url, callback=self.parse_list)

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
        table_context = _table_context_text(table)
        inferred_year = _parse_year(table_context)
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

            data = await self._build_item_data(
                conn,
                source_url,
                school,
                provinces,
                header_map,
                cells,
                inferred_year,
                table_context,
            )
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
        table_context: str,
    ) -> dict | None:
        year = _parse_year(_cell_text(cells, _column_index(header_map, ("年份",)))) or inferred_year
        province_name = _cell_text(cells, _column_index(header_map, ("省份", "录取省份")))
        major_name = _cell_text(cells, _column_index(header_map, ("专业名称", "专业")))
        if year is None or not major_name:
            return None

        province_id = provinces.get(_normalize_province_name(province_name)) if province_name else None
        if province_id is None:
            province_id = _infer_province_id(table_context, provinces)
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
        subject_category_id = await self._resolve_subject_category(_canonical_subject_category(subject_category_raw))
        batch_raw = _cell_text(cells, _column_index(header_map, ("类别", "批次", "录取批次"))) or "普通类"
        batch_info = normalize_batch(batch_raw)
        selection_requirement = _cell_text(cells, _column_index(header_map, ("选考要求", "选科要求")))
        min_score = _parse_score(_cell_text(cells, _column_index(header_map, ("最低分", "最低分数"))))
        avg_score = _parse_score(_cell_text(cells, _column_index(header_map, ("平均分",))))
        max_score = _parse_score(_cell_text(cells, _column_index(header_map, ("最高分",))))
        min_rank = await self._derive_rank(
            conn,
            province_id=province_id,
            year=year,
            subject_category_id=subject_category_id,
            score=min_score,
        )
        avg_rank = await self._derive_rank(
            conn,
            province_id=province_id,
            year=year,
            subject_category_id=subject_category_id,
            score=avg_score,
        )
        max_rank = await self._derive_rank(
            conn,
            province_id=province_id,
            year=year,
            subject_category_id=subject_category_id,
            score=max_score,
        )

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
            "min_score": min_score,
            "min_rank": min_rank,
            "min_rank_source": "score_segments" if min_rank is not None else None,
            "min_rank_is_derived": min_rank is not None,
            "avg_score": avg_score,
            "avg_rank": avg_rank,
            "max_score": max_score,
            "max_rank": max_rank,
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

    async def _derive_rank(
        self,
        conn: asyncpg.Connection,
        *,
        province_id: int,
        year: int,
        subject_category_id: int | None,
        score: int | None,
    ) -> int | None:
        if score is None:
            return None

        cache_key = (province_id, year, subject_category_id, score)
        if cache_key in self._score_rank_cache:
            return self._score_rank_cache[cache_key]

        row = await find_score_segment_rank(conn, province_id, year, subject_category_id, score)
        rank = int(row["cumulative_count"]) if row is not None else None
        self._score_rank_cache[cache_key] = rank
        return rank


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


def _table_context_text(table) -> str:
    parts = _leading_table_context_parts(table)
    node = table
    for _ in range(6):
        parts.extend(_previous_context_parts(node))
        node = getattr(node, "parent", None)
        if node is None:
            break
    return " ".join(dict.fromkeys(part for part in parts if part))


def _leading_table_context_parts(table) -> list[str]:
    parts = []
    for row in table.css("tr"):
        texts = [_node_text(cell) for cell in row.css("th, td")]
        if not any(texts):
            continue
        if _looks_like_header(texts):
            break
        joined = "".join(texts)
        if _parse_year(joined) is not None:
            parts.append(joined)
    return parts


def _previous_context_parts(node) -> list[str]:
    parts = []
    previous = getattr(node, "previous", None)
    for _ in range(8):
        if previous is None:
            break
        text = str(previous.get_all_text(separator="", strip=True))
        if text:
            parts.append(text)
        previous = getattr(previous, "previous", None)
    return parts


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


def _canonical_subject_category(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    if "物理" in normalized:
        return "物理类"
    if "历史" in normalized:
        return "历史类"
    if "理工" in normalized or "理科" in normalized:
        return "理科"
    if "文史" in normalized or "文科" in normalized:
        return "文科"
    if normalized in {"普通类", "不分文理"}:
        return ""
    return normalized


def _infer_province_id(text: str, provinces: dict[str, int]) -> int | None:
    normalized_text = _normalize_province_name(text)
    for province_name, province_id in sorted(provinces.items(), key=lambda item: len(item[0]), reverse=True):
        if province_name and province_name in normalized_text:
            return province_id
    return None


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
