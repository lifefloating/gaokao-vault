from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.enrollment import upsert_timeline
from gaokao_vault.models.enrollment import TimelineItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

PROVINCE_IDS = list(range(1, 32))


class TimelineSpider(BaseGaokaoSpider):
    """Crawl volunteer fill timelines by province."""

    name: str = "timeline_spider"
    task_type: str = TaskType.TIMELINES

    async def start_requests(self):
        current_year = datetime.now().year
        for province_id in PROVINCE_IDS:
            url = f"{BASE_URL}/z/gkbmfslq/zytb.jsp"
            yield Request(
                url,
                callback=self.parse,
                meta={"province_id": province_id, "year": current_year},
                params={"provinceId": str(province_id), "year": str(current_year)},
            )

    async def parse(self, response: Response):
        if response.request is None:
            return
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")

        if not province_id or not year:
            return

        for row in response.css("table.timeline-table tr"):
            cells = row.css("td")
            if len(cells) < 2:
                continue

            batch = cells[0].css("::text").get("").strip()
            if not batch:
                continue

            start_text = cells[1].css("::text").get("").strip() if len(cells) > 1 else ""
            end_text = cells[2].css("::text").get("").strip() if len(cells) > 2 else ""
            note_text = cells[3].css("::text").get("").strip() if len(cells) > 3 else None

            start_time = _parse_datetime(start_text)
            end_time = _parse_datetime(end_text)

            data = {
                "province_id": province_id,
                "year": year,
                "batch": batch,
                "start_time": start_time,
                "end_time": end_time,
                "note": note_text if note_text else None,
            }

            item = validate_item(TimelineItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="timelines",
                    unique_keys={
                        "province_id": province_id,
                        "year": year,
                        "batch": batch,
                    },
                    upsert_fn=upsert_timeline,
                )


def _parse_datetime(text: str) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
