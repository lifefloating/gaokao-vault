from __future__ import annotations

import logging
import re

from scrapling.spiders import Response

from gaokao_vault.constants import TaskType
from gaokao_vault.db.queries.majors import (
    find_major_by_code,
    find_major_by_source_id,
    find_majors_by_name,
    refresh_school_major_strength_rollup,
    upsert_school_major_strength_signal,
)
from gaokao_vault.models.major import SchoolMajorStrengthSignalItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.school_major_spider import SchoolMajorSpider

logger = logging.getLogger(__name__)


class MajorStrengthSignalSpider(SchoolMajorSpider):
    """Crawl authoritative school-major strength labels from school major pages."""

    name: str = "major_strength_signal_spider"
    task_type: str = TaskType.MAJOR_STRENGTH_SIGNALS

    async def _resolve_major_id(
        self,
        conn,
        *,
        school_id: int,
        sch_id: int,
        source_id: str | None,
        data_code: str | None,
        href_code: str | None,
        name: str | None,
        page_url: str,
    ) -> int | None:
        if source_id:
            row = await find_major_by_source_id(conn, source_id)
            if row is not None:
                return row["id"]

        for code in dict.fromkeys(code for code in (data_code, href_code) if code):
            row = await find_major_by_code(conn, code)
            if row is not None:
                return row["id"]

        if name:
            rows = await find_majors_by_name(conn, name)
            if len(rows) == 1:
                return rows[0]["id"]

        logger.warning(
            "Unable to resolve strength-signal major school_id=%s sch_id=%s data_code=%s href_code=%s name=%s url=%s",
            school_id,
            sch_id,
            data_code,
            href_code,
            name,
            page_url,
        )
        return None

    async def parse(self, response: Response):
        if response.status == 404 or response.request is None:
            return

        school_id = response.request.meta.get("school_id")
        sch_id = response.request.meta.get("sch_id")
        if not school_id or not sch_id:
            return

        candidates = self._extract_major_candidates(response)
        async with (await self._get_pool()).acquire() as conn:
            for candidate in candidates:
                evidence = _extract_strength_signal(candidate.get("raw_text") or candidate.get("name") or "")
                if evidence is None:
                    continue

                major_id = await self._resolve_major_id(
                    conn,
                    school_id=school_id,
                    sch_id=sch_id,
                    source_id=candidate["source_id"],
                    data_code=candidate["data_code"],
                    href_code=candidate["href_code"],
                    name=candidate["name"],
                    page_url=response.url,
                )
                if major_id is None:
                    continue

                data = {
                    "school_id": school_id,
                    "major_id": major_id,
                    "signal_type": evidence["signal_type"],
                    "signal_level": evidence["signal_level"],
                    "strength_score": evidence["strength_score"],
                    "source_url": response.url,
                    "evidence_title": evidence["evidence_title"],
                    "evidence_year": _infer_year(response.url),
                }
                item = validate_item(SchoolMajorStrengthSignalItem, data)
                if item:
                    yield item
                    await self.process_item(
                        item,
                        entity_type="school_major_strength_signals",
                        unique_keys={
                            "school_id": school_id,
                            "major_id": major_id,
                            "signal_type": evidence["signal_type"],
                            "signal_level": evidence["signal_level"],
                            "evidence_year": item.get("evidence_year"),
                        },
                        upsert_fn=upsert_school_major_strength_signal,
                    )

    def _extract_major_candidates(self, response: Response) -> list[dict[str, str | None]]:
        candidates = super()._extract_major_candidates(response)
        links = response.css("div.yxk-zyjs-tab ul li a, div.major-list a.major-link")
        for candidate, link in zip(candidates, links, strict=True):
            raw_text = _clean_text(" ".join(link.css("::text").getall()))
            candidate["raw_text"] = raw_text
            candidate["name"] = _strip_strength_labels(raw_text) or candidate["name"]
        return candidates

    async def on_close(self) -> None:
        try:
            async with (await self._get_pool()).acquire() as conn:
                await refresh_school_major_strength_rollup(conn, crawl_task_id=self.crawl_task_id)
        except Exception:
            logger.exception("Failed to refresh school major strength rollup")
            self._stats["failed"] += 1
        await super().on_close()


def _extract_strength_signal(text: str) -> dict[str, object] | None:
    value = _clean_text(text)
    if "国家级" in value and "一流本科专业" in value:
        return {
            "signal_type": "first_class_major",
            "signal_level": "national",
            "strength_score": 100,
            "evidence_title": "国家级一流本科专业建设点",
        }
    if "省级" in value and "一流本科专业" in value:
        return {
            "signal_type": "first_class_major",
            "signal_level": "provincial",
            "strength_score": 70,
            "evidence_title": "省级一流本科专业建设点",
        }
    if "国家特色专业" in value or "国家级特色专业" in value:
        return {
            "signal_type": "featured_major",
            "signal_level": "national",
            "strength_score": 80,
            "evidence_title": "国家级特色专业",
        }
    return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _strip_strength_labels(text: str) -> str:
    value = _clean_text(text)
    for label in (
        "国家级一流本科专业建设点",
        "省级一流本科专业建设点",
        "国家级特色专业",
        "国家特色专业",
    ):
        value = value.replace(label, "")
    return _clean_text(value)


def _infer_year(text: str) -> int | None:
    match = re.search(r"20\d{2}", text)
    return int(match.group(0)) if match else None


# Re-exported for tests and future parser reuse.
__all__ = [
    "MajorStrengthSignalSpider",
    "find_major_by_code",
    "find_major_by_source_id",
    "find_majors_by_name",
]
