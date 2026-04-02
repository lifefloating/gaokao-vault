from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.scores import upsert_score_line
from gaokao_vault.models.score import ScoreLineItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

# Province codes for the 31 provinces (matching seed data)
PROVINCE_IDS = list(range(1, 32))
YEAR_START = 2015
YEAR_END = datetime.now().year


class ScoreLineSpider(BaseGaokaoSpider):
    """Crawl admission score lines: 31 provinces x year range."""

    name: str = "score_line_spider"
    task_type: str = TaskType.SCORE_LINES

    async def start_requests(self):
        for province_id in PROVINCE_IDS:
            for year in range(YEAR_START, YEAR_END + 1):
                url = f"{BASE_URL}/z/gkbmfslq/pcx.jsp?provinceId={province_id}&year={year}"
                yield Request(
                    url,
                    callback=self.parse,
                    meta={"province_id": province_id, "year": year},
                )

    async def parse(self, response: Response):
        if response.request is None:
            return
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")

        if not province_id or not year:
            return

        for row in response.css("table.score-table tr"):
            cells = row.css("td")
            if len(cells) < 3:
                continue

            batch = cells[0].css("::text").get("").strip()
            subject_text = cells[1].css("::text").get("").strip()
            score_text = cells[2].css("::text").get("").strip()

            if not batch:
                continue

            # Map subject text to subject_category_id
            subject_map = {"理科": 1, "文科": 2, "综合": 3, "物理类": 4, "历史类": 5}
            subject_category_id = subject_map.get(subject_text)

            score = None
            if score_text and score_text.isdigit():
                score = int(score_text)

            note_el = cells[3].css("::text") if len(cells) > 3 else None
            note = note_el.get("").strip() if note_el else None

            data = {
                "province_id": province_id,
                "year": year,
                "subject_category_id": subject_category_id,
                "batch": batch,
                "score": score,
                "note": note,
            }

            item = validate_item(ScoreLineItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="score_lines",
                    unique_keys={
                        "province_id": province_id,
                        "year": year,
                        "subject_category_id": subject_category_id,
                        "batch": batch,
                    },
                    upsert_fn=upsert_score_line,
                )
