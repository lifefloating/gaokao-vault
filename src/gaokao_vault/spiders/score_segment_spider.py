from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import ClassVar
from urllib.parse import urljoin

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response

from gaokao_vault.config import AppConfig, CrawlConfig, DatabaseConfig
from gaokao_vault.constants import TaskType
from gaokao_vault.db.queries.scores import batch_upsert_score_segments
from gaokao_vault.models.score import ScoreSegmentItem
from gaokao_vault.pipeline.hasher import compute_content_hash
from gaokao_vault.pipeline.sink import BatchSink
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.dxsbb import DXSBB_BASE_URL
from gaokao_vault.spiders.response_utils import response_text
from gaokao_vault.spiders.scope import iter_crawl_years, load_province_targets
from gaokao_vault.vision.analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)

YEAR_START = 2018
YEAR_END = datetime.now().year
EOL_SEGMENT_INDEX_URL = "https://www.eol.cn/e_html/gk/gkfsd/"
EOL_SEGMENT_YEAR_INDEX_URL_TEMPLATE = "https://www.eol.cn/e_html/gk/gkfsd/{year}.shtml"
EOL_DATA_SOURCE = "gaokao.eol.cn"
DXSBB_SEGMENT_INDEX_URL = f"{DXSBB_BASE_URL}/news/list_223.html"
DXSBB_DATA_SOURCE = "dxsbb.com"
_SEGMENT_LINK_KEYWORDS = ("一分一段", "一分段", "成绩分段", "成绩分数段", "成绩分布", "分段表")
_SUBJECT_HINTS = ("物理类", "历史类", "理科", "文科", "综合", "艺术类", "体育类")


class ScoreSegmentSpider(BaseGaokaoSpider):
    """Crawl score segment tables (一分一段表). Uses BatchSink for large volumes."""

    name: str = "score_segment_spider"
    task_type: str = TaskType.SCORE_SEGMENTS
    allowed_domains: ClassVar[set[str]] = {"www.eol.cn", "gaokao.eol.cn", "www.dxsbb.com", "dxsbb.com"}

    concurrent_requests = 3
    download_delay = 2.0

    def __init__(
        self,
        db_config: DatabaseConfig,
        crawl_task_id: int,
        mode: str = "full",
        config: CrawlConfig | None = None,
        app_config: AppConfig | None = None,
        **kwargs,
    ):
        super().__init__(
            db_config=db_config,
            crawl_task_id=crawl_task_id,
            mode=mode,
            config=config,
            app_config=app_config,
            **kwargs,
        )
        self._sink: BatchSink | None = None
        self._app_config = app_config

    def configure_sessions(self, manager) -> None:
        manager.add(
            "http",
            FetcherSession(
                timeout=30,
                headers={
                    "Referer": "https://www.eol.cn/e_html/gk/gkfsd/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            ),
        )

    async def on_start(self, resuming: bool = False):
        pool = await self._get_pool()
        self._sink = BatchSink(
            pool=pool,
            flush_fn=self._flush_batch,
            batch_size=500,
        )

    @staticmethod
    async def _flush_batch(conn, rows):
        return await batch_upsert_score_segments(conn, rows)

    async def start_requests(self):
        provinces = await load_province_targets(await self._get_pool())
        years = list(iter_crawl_years(mode=self.mode, full_start_year=YEAR_START, current_year=YEAR_END))
        province_meta = [
            {"id": province.id, "name": province.name, "code": province.url_value} for province in provinces
        ]

        index_urls = [EOL_SEGMENT_INDEX_URL]
        latest_index_year = _latest_eol_index_year()
        for year in years:
            if year < latest_index_year:
                index_urls.append(EOL_SEGMENT_YEAR_INDEX_URL_TEMPLATE.format(year=year))

        for url in dict.fromkeys(index_urls):
            yield Request(
                url,
                callback=self.parse_index,
                meta={"provinces": province_meta, "years": years},
            )

        yield Request(
            DXSBB_SEGMENT_INDEX_URL,
            callback=self.parse_dxsbb_index,
            meta={"provinces": province_meta, "years": years},
        )

    async def parse_index(self, response: Response):
        if response.request is None:
            return

        meta = response.request.meta
        province_by_name = {province["name"]: province for province in meta.get("provinces") or []}
        allowed_years = set(meta.get("years") or [])

        for province_name, links in _index_blocks(response):
            province = province_by_name.get(province_name)
            if province is None:
                continue

            for href, title in links:
                if not href or "/e_html/gk/gkfsd/" in href:
                    continue
                if not _looks_like_segment_link(title):
                    continue

                year = _extract_year(f"{title} {href}")
                if year is None or year not in allowed_years:
                    continue

                yield Request(
                    href,
                    callback=self.parse,
                    meta={
                        "province_id": province["id"],
                        "province_name": province_name,
                        "province_code": province["code"],
                        "year": year,
                        "subject_hint": _extract_subject_hint(title),
                        "data_source": EOL_DATA_SOURCE,
                    },
                )

    async def parse_dxsbb_index(self, response: Response):
        if response.request is None or response.status == 404:
            return

        meta = response.request.meta
        province_by_name = {province["name"]: province for province in meta.get("provinces") or []}
        allowed_years = set(meta.get("years") or [])
        seen_urls: set[str] = set()

        for link in response.css("a[href]"):
            href = link.attrib.get("href", "").strip()
            title = _node_text(link).strip()
            if not href or not title:
                continue

            province = _find_province_for_text(title, province_by_name)
            if province is None:
                continue

            url = urljoin(DXSBB_BASE_URL, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            if "/news/list_" in url:
                yield Request(url, callback=self.parse_dxsbb_index, meta=meta)
                continue

            if not _looks_like_segment_link(title):
                continue

            year = _extract_year(f"{title} {href}")
            if year is not None and year not in allowed_years:
                continue

            if year is None:
                continue

            yield Request(
                url,
                callback=self.parse_dxsbb_article,
                meta={
                    "province_id": province["id"],
                    "province_name": province["name"],
                    "province_code": province["code"],
                    "year": year,
                    "subject_hint": _extract_subject_hint(title),
                    "data_source": DXSBB_DATA_SOURCE,
                    "title": title,
                },
            )

    async def parse(self, response: Response):
        if response.request is None:
            return
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")

        if not province_id or not year:
            return

        parsed_eol_rows = 0
        async for item in self._parse_eol_article(response, province_id=province_id, year=year):
            parsed_eol_rows += 1
            yield item
        if parsed_eol_rows:
            return

        for row in response.css("table.segment-table tr"):
            cells = row.css("td")
            if len(cells) < 3:
                continue

            score_text = cells[0].css("::text").get("").strip()
            seg_text = cells[1].css("::text").get("").strip()
            cum_text = cells[2].css("::text").get("").strip()

            if not score_text or not score_text.isdigit():
                continue

            subject_text = cells[3].css("::text").get("").strip() if len(cells) > 3 else ""
            subject_category_id = await self._resolve_subject_category(subject_text)

            data = {
                "province_id": province_id,
                "year": year,
                "subject_category_id": subject_category_id,
                "score": int(score_text),
                "segment_count": int(seg_text) if seg_text.isdigit() else 0,
                "cumulative_count": int(cum_text) if cum_text.isdigit() else 0,
            }

            item = validate_item(ScoreSegmentItem, data)
            if item:
                yield item
                await self._add_to_sink(item)

    async def _parse_eol_article(self, response: Response, *, province_id: int, year: int):
        title = _node_text(response.css("div.title")).strip() or _node_text(response.css("title")).strip()
        meta = response.request.meta if response.request else {}
        subject_hint = meta.get("subject_hint") or _extract_subject_hint(title)
        subject_category_id = await self._resolve_subject_category(subject_hint or "")

        for table in _segment_tables(response):
            if not _looks_like_segment_table(table):
                continue
            for row in table.css("tr"):
                cells = row.css("td, th")
                if len(cells) < 3:
                    continue
                values = [_node_text(cell).strip() for cell in cells[:3]]
                if not values or "分数" in values[0]:
                    continue

                score = _parse_score(values[0])
                segment_count = _parse_count(values[1])
                cumulative_count = _parse_count(values[2])
                if score is None or segment_count is None or cumulative_count is None:
                    continue

                data = {
                    "province_id": province_id,
                    "year": year,
                    "subject_category_id": subject_category_id,
                    "score": score,
                    "segment_count": segment_count,
                    "cumulative_count": cumulative_count,
                }
                item = validate_item(ScoreSegmentItem, data)
                if item:
                    yield item
                    await self._add_to_sink(item)

    async def parse_dxsbb_article(self, response: Response):
        if response.request is None or response.status == 404:
            return

        meta = response.request.meta
        province_id = meta.get("province_id")
        province_name = meta.get("province_name") or ""
        year = meta.get("year")
        subject_hint = meta.get("subject_hint") or _extract_subject_hint(
            meta.get("title") or _node_text(response.css("#article h1, h1, title"))
        )

        if not province_id or not year:
            return

        parsed_rows = 0
        async for item in self._parse_dxsbb_article_tables(
            response,
            province_id=province_id,
            year=year,
            subject_hint=subject_hint,
        ):
            parsed_rows += 1
            yield item
        if parsed_rows:
            return

        for image_url in _dxsbb_segment_image_urls(response):
            records = await self._analyze_dxsbb_segment_image(
                image_url,
                province_name=province_name,
                year=year,
                subject_hint=subject_hint,
            )
            for record in records:
                item = await self._build_dxsbb_segment_item(
                    record,
                    province_id=province_id,
                    year=year,
                    fallback_subject_hint=subject_hint,
                )
                if item is None:
                    continue
                yield item
                await self._add_to_sink(item)

    async def _parse_dxsbb_article_tables(
        self,
        response: Response,
        *,
        province_id: int,
        year: int,
        subject_hint: str | None,
    ):
        for table in response.css("#article .content table, #article table, .content table"):
            if not _looks_like_segment_table(table):
                continue
            async for item in self._parse_segment_table(
                table, province_id=province_id, year=year, subject_hint=subject_hint
            ):
                yield item

    async def _parse_segment_table(self, table, *, province_id: int, year: int, subject_hint: str | None):
        header_map: dict[str, int] | None = None
        for row in table.css("tr"):
            cells = row.css("td, th")
            if len(cells) < 3:
                continue

            values = [_node_text(cell).strip() for cell in cells]
            if _looks_like_segment_header(values):
                header_map = {value: index for index, value in enumerate(values) if value}
                continue

            score_index = _column_index(header_map, ("分数", "分数段"), 0)
            segment_index = _column_index(header_map, ("本段人数", "人数", "同分人数"), 1)
            cumulative_index = _column_index(header_map, ("累计人数", "累计", "位次"), 2)
            category_index = _column_index(header_map, ("科类", "类别"), -1)

            score = _parse_score(_cell_text(values, score_index))
            segment_count = _parse_count(_cell_text(values, segment_index))
            cumulative_count = _parse_count(_cell_text(values, cumulative_index))
            if score is None or segment_count is None or cumulative_count is None:
                continue

            category = _cell_text(values, category_index) or subject_hint or ""
            subject_category_id = await self._resolve_subject_category(category)
            data = {
                "province_id": province_id,
                "year": year,
                "subject_category_id": subject_category_id,
                "score": score,
                "segment_count": segment_count,
                "cumulative_count": cumulative_count,
            }
            item = validate_item(ScoreSegmentItem, data)
            if item:
                yield item
                await self._add_to_sink(item)

    async def _build_dxsbb_segment_item(
        self,
        record: dict,
        *,
        province_id: int,
        year: int,
        fallback_subject_hint: str | None,
    ) -> dict | None:
        score = _parse_score(str(record.get("score") or ""))
        segment_count = _parse_count(str(record.get("segment_count") or ""))
        cumulative_count = _parse_count(str(record.get("cumulative_count") or ""))
        if score is None or segment_count is None or cumulative_count is None:
            return None

        category = str(record.get("category") or fallback_subject_hint or "")
        subject_category_id = await self._resolve_subject_category(category)
        return validate_item(
            ScoreSegmentItem,
            {
                "province_id": province_id,
                "year": year,
                "subject_category_id": subject_category_id,
                "score": score,
                "segment_count": segment_count,
                "cumulative_count": cumulative_count,
            },
        )

    async def _analyze_dxsbb_segment_image(
        self,
        image_url: str,
        *,
        province_name: str,
        year: int,
        subject_hint: str | None,
    ) -> list[dict]:
        if self._app_config is None:
            logger.warning(
                "No OpenAI config available; skipping dxsbb image segment extraction for %s %d", province_name, year
            )
            return []

        prompt_path = Path(__file__).parents[1] / "vision" / "prompts" / "score_segment_extract.txt"
        prompt = prompt_path.read_text(encoding="utf-8").format(
            province_name=province_name,
            year=year,
            subject_hint=subject_hint or "",
        )
        analyzer = VisionAnalyzer(self._app_config.openai)
        return await analyzer.analyze_image_url(
            image_url,
            prompt=prompt,
            province_name=province_name,
            year=year,
        )

    async def _add_to_sink(self, item: dict) -> None:
        item["content_hash"] = compute_content_hash(item)
        item["crawl_task_id"] = self.crawl_task_id
        if self._sink:
            before = self._sink.total_flushed
            await self._sink.add(item)
            self._stats["updated"] += self._sink.total_flushed - before

    async def on_close(self) -> None:
        if self._sink:
            before = self._sink.total_flushed
            await self._sink.flush()
            self._stats["updated"] += self._sink.total_flushed - before
        await super().on_close()


def _latest_eol_index_year() -> int:
    now = datetime.now()
    return now.year if now.month >= 7 else now.year - 1


def _node_text(node) -> str:
    return "".join(part.strip() for part in node.css("::text").getall() if part.strip())


def _segment_tables(response: Response):
    editor_tables = response.css("div.TRS_Editor table")
    if editor_tables:
        return editor_tables
    return response.css("table")


def _index_blocks(response: Response) -> list[tuple[str, list[tuple[str, str]]]]:
    blocks = []
    for block in response.css("div.chengshi"):
        province_name = _node_text(block.css(".chengshi-head span")).strip()
        links = [(link.attrib.get("href", "").strip(), _node_text(link)) for link in block.css("a")]
        blocks.append((province_name, links))
    if blocks:
        return blocks
    return _index_blocks_from_html(response_text(response))


def _index_blocks_from_html(html: str) -> list[tuple[str, list[tuple[str, str]]]]:
    blocks = []
    for chunk in html.split('<div class="chengshi">')[1:]:
        province_match = re.search(r"<div class=\"chengshi-head\">.*?<span>(.*?)</span>", chunk, re.S)
        if province_match is None:
            continue
        province_name = _strip_tags(province_match.group(1))
        links = [
            (unescape(match.group(1).strip()), _strip_tags(match.group(2)))
            for match in re.finditer(r"<a\s+[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", chunk, re.S)
        ]
        blocks.append((province_name, links))
    return blocks


def _find_province_for_text(text: str, province_by_name: dict[str, dict]) -> dict | None:
    matches = [province for name, province in province_by_name.items() if name and name in text]
    return matches[0] if matches else None


def _strip_tags(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _looks_like_segment_link(text: str) -> bool:
    return any(keyword in text for keyword in _SEGMENT_LINK_KEYWORDS)


def _looks_like_segment_table(table) -> bool:
    first_row_text = _node_text(table.css("tr")).strip()
    return "分数" in first_row_text and ("人数" in first_row_text or "累计" in first_row_text)


def _looks_like_segment_header(values: list[str]) -> bool:
    joined = "|".join(values)
    return "分数" in joined and ("人数" in joined or "累计" in joined or "位次" in joined)


def _column_index(header_map: dict[str, int] | None, names: tuple[str, ...], default: int) -> int:
    if header_map is None:
        return default
    for name in names:
        for header, index in header_map.items():
            if name in header:
                return index
    return default


def _cell_text(values: list[str], index: int) -> str:
    if index < 0 or index >= len(values):
        return ""
    return values[index]


def _dxsbb_segment_image_urls(response: Response) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for image in response.css("#article .content img[src], #article img[src], .content img[src]"):
        src = image.attrib.get("src", "").strip()
        alt = image.attrib.get("alt", "").strip()
        if not src:
            continue
        if not (_looks_like_segment_link(alt) or _looks_like_segment_link(src) or "uploads" in src):
            continue
        url = urljoin(DXSBB_BASE_URL, src)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_year(text: str) -> int | None:
    match = re.search(r"20[12]\d", text)
    return int(match.group(0)) if match else None


def _extract_subject_hint(text: str) -> str | None:
    for hint in _SUBJECT_HINTS:
        if hint in text:
            return hint
    return None


def _parse_score(text: str) -> int | None:
    match = re.search(r"\d+", text.replace(",", ""))
    return int(match.group(0)) if match else None


def _parse_count(text: str) -> int | None:
    normalized = text.replace(",", "").strip()
    return int(normalized) if normalized.isdigit() else None
