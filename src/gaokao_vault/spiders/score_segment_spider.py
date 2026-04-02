from __future__ import annotations

import logging
from datetime import datetime

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.scores import batch_upsert_score_segments
from gaokao_vault.models.score import ScoreSegmentItem
from gaokao_vault.pipeline.hasher import compute_content_hash
from gaokao_vault.pipeline.sink import BatchSink
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BaseGaokaoSpider

logger = logging.getLogger(__name__)

PROVINCE_IDS = list(range(1, 32))
YEAR_START = 2018
YEAR_END = datetime.now().year


class ScoreSegmentSpider(BaseGaokaoSpider):
    """Crawl score segment tables (一分一段表). Uses BatchSink for large volumes."""

    name: str = "score_segment_spider"
    task_type: str = TaskType.SCORE_SEGMENTS

    concurrent_requests = 3
    download_delay = 2.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sink: BatchSink | None = None

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
        for province_id in PROVINCE_IDS:
            for year in range(YEAR_START, YEAR_END + 1):
                url = f"{BASE_URL}/gkxx/zc/ss/"
                yield Request(
                    url,
                    callback=self.parse,
                    meta={"province_id": province_id, "year": year},
                    params={
                        "provinceId": str(province_id),
                        "year": str(year),
                        "type": "segment",
                    },
                )

    async def parse(self, response: Response):
        if response.request is None:
            return
        province_id = response.request.meta.get("province_id")
        year = response.request.meta.get("year")

        if not province_id or not year:
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
            subject_map = {"理科": 1, "文科": 2, "综合": 3, "物理类": 4, "历史类": 5}
            subject_category_id = subject_map.get(subject_text)

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
                item["content_hash"] = compute_content_hash(item)
                item["crawl_task_id"] = self.crawl_task_id
                if self._sink:
                    await self._sink.add(item)

    async def on_close(self) -> None:
        if self._sink:
            await self._sink.flush()
        await super().on_close()
