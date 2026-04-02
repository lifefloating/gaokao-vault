from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from scrapling.spiders import Request, Response

from gaokao_vault.config import AppConfig, CrawlConfig, DatabaseConfig
from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.scores import upsert_score_line
from gaokao_vault.models.score import ScoreLineItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.vision.analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "gaokao_score_screenshots"


def _make_screenshot_action(province_name: str, year: int) -> tuple[Callable, Path]:
    """Build a page_action function and the screenshot destination path."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    timestamp = int(time.time() * 1000)
    filename = f"{province_name}_{year}_{timestamp}.png"
    filepath = SCREENSHOT_DIR / filename

    async def take_screenshot(page):
        await page.screenshot(path=str(filepath), full_page=True)

    return take_screenshot, filepath


class ScoreLineSpider(BaseGaokaoSpider):
    """Crawl admission score lines via full-page screenshot + AI Vision analysis."""

    name: str = "score_line_spider"
    task_type: str = TaskType.SCORE_LINES

    def __init__(
        self,
        db_config: DatabaseConfig,
        crawl_task_id: int,
        mode: str = "full",
        config: CrawlConfig | None = None,
        app_config: AppConfig | None = None,
        **kwargs,
    ):
        super().__init__(db_config=db_config, crawl_task_id=crawl_task_id, mode=mode, config=config, **kwargs)
        self._app_config = app_config
        self._province_map: dict[str, int] | None = None
        self._subject_category_map: dict[str, int] | None = None

    async def _load_province_map(self) -> dict[str, int]:
        """Query the provinces table and build a name → id mapping."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM provinces")
            return {row["name"]: row["id"] for row in rows}

    async def _load_subject_category_map(self) -> dict[str, int]:
        """Query the subject_categories table and build a name → id mapping."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM subject_categories")
            return {row["name"]: row["id"] for row in rows}

    # ------------------------------------------------------------------
    # start_requests  (Task 5.1)
    # ------------------------------------------------------------------

    async def start_requests(self):
        """Request the summary page pcx.jsp (single page, no province_id loop)."""
        url = f"{BASE_URL}/z/gkbmfslq/pcx.jsp"
        yield Request(url, callback=self.parse)

    # ------------------------------------------------------------------
    # parse  (Task 5.2)
    # ------------------------------------------------------------------

    async def parse(self, response: Response):
        """Parse the summary page table01 table, extract detail links per province/year."""
        if self._province_map is None:
            self._province_map = await self._load_province_map()

        for row in response.css("table.table01 tr"):
            cells = row.css("td")
            if not cells:
                continue

            # First cell contains the province name
            province_name = cells[0].css("::text").get("").strip()
            if not province_name:
                continue

            province_id = self._province_map.get(province_name)
            if province_id is None:
                logger.warning("Province name '%s' not found in provinces table, skipping", province_name)
                continue

            # Remaining cells contain year links; each "查看" anchor has an href
            for cell in cells[1:]:
                link_el = cell.css("a")
                if not link_el:
                    logger.debug("No '查看' link for province %s in a year column, skipping", province_name)
                    continue

                href = link_el[0].attrib.get("href", "").strip()
                if not href:
                    logger.debug("Empty href for province %s, skipping", province_name)
                    continue

                # Try to extract year from the link text or URL
                year = self._extract_year_from_cell(cell, href)
                if year is None:
                    continue

                detail_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                action, screenshot_path = _make_screenshot_action(province_name, year)
                yield Request(
                    detail_url,
                    callback=self.parse_detail,
                    dont_filter=True,
                    meta={
                        "province_id": province_id,
                        "province_name": province_name,
                        "year": year,
                        "screenshot_path": str(screenshot_path),
                    },
                    page_action=action,
                )

    @staticmethod
    def _extract_year_from_cell(cell, href: str) -> int | None:
        """Try to extract the year from the cell header or the URL query string."""
        import re
        from urllib.parse import parse_qs, urlparse

        # Try URL query param first
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        if "year" in qs:
            try:
                return int(qs["year"][0])
            except (ValueError, IndexError):
                pass

        # Try to find a 4-digit year in the href
        match = re.search(r"20[12]\d", href)
        if match:
            return int(match.group())

        # Try the cell text
        text = cell.css("::text").get("").strip()
        match = re.search(r"20[12]\d", text)
        if match:
            return int(match.group())

        return None

    # ------------------------------------------------------------------
    # parse_detail  (Task 5.3)
    # ------------------------------------------------------------------

    def _resolve_subject_category(self, category_text: str, province_name: str, year: int) -> int | None:
        """Map a category text to its subject_category_id, or None if unknown."""
        if not category_text:
            return None
        sc_id = (self._subject_category_map or {}).get(category_text)
        if sc_id is None:
            logger.warning(
                "Unknown category '%s' for %s %d, setting subject_category_id to null",
                category_text,
                province_name,
                year,
            )
        return sc_id

    async def _analyze_screenshot(self, screenshot_path: Path, province_name: str, year: int) -> list[dict]:
        """Run VisionAnalyzer on a screenshot, returning parsed records."""
        openai_config = self._app_config.openai if self._app_config else None
        if openai_config is None:
            logger.error("No OpenAI config available, cannot analyze screenshot for %s %d", province_name, year)
            return []

        analyzer = VisionAnalyzer(openai_config)
        records = await analyzer.analyze(screenshot_path, province_name, year)
        if not records:
            logger.warning("No records extracted from screenshot for %s %d", province_name, year)
        return records

    async def parse_detail(self, response: Response):
        """Process a detail page whose screenshot was taken via page_action."""
        if response.request is None:
            return

        meta = response.request.meta
        screenshot_path_str: str = meta.get("screenshot_path", "")
        province_id: int = meta.get("province_id", 0)
        province_name: str = meta.get("province_name", "")
        year: int = meta.get("year", 0)

        if not screenshot_path_str or not province_id or not year:
            logger.error("Missing meta for parse_detail, skipping: %s", meta)
            return

        screenshot_path = Path(screenshot_path_str)
        if not screenshot_path.exists():
            logger.error(
                "Screenshot file not found at %s, skipping detail for %s %d",
                screenshot_path,
                province_name,
                year,
            )
            return

        records = await self._analyze_screenshot(screenshot_path, province_name, year)

        # Load subject_category mapping (cached)
        if self._subject_category_map is None:
            self._subject_category_map = await self._load_subject_category_map()

        for record in records:
            subject_category_id = self._resolve_subject_category(record.get("category", ""), province_name, year)
            data = {
                "province_id": province_id,
                "year": year,
                "subject_category_id": subject_category_id,
                "batch": record.get("batch", ""),
                "score": record.get("score"),
                "note": record.get("note"),
                "special_name": record.get("special_name"),
            }

            item = validate_item(ScoreLineItem, data)
            if item is None:
                continue

            yield item
            await self.process_item(
                item,
                entity_type="score_lines",
                unique_keys={
                    "province_id": province_id,
                    "year": year,
                    "subject_category_id": subject_category_id,
                    "batch": item["batch"],
                    "special_name": item.get("special_name"),
                },
                upsert_fn=upsert_score_line,
            )

        # Clean up screenshot file
        try:
            screenshot_path.unlink()
        except OSError:
            logger.warning("Failed to delete screenshot %s", screenshot_path)
