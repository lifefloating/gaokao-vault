from __future__ import annotations

import asyncio
import logging
import os

import asyncpg

from gaokao_vault.config import AppConfig, CrawlConfig, DatabaseConfig
from gaokao_vault.constants import PHASE2_TYPES, PHASE3_TYPES, TaskType
from gaokao_vault.scheduler.task_manager import TaskManager
from gaokao_vault.spiders.base import BaseGaokaoSpider
from gaokao_vault.spiders.charter_spider import CharterSpider
from gaokao_vault.spiders.enrollment_plan_spider import EnrollmentPlanSpider
from gaokao_vault.spiders.interpretation_spider import InterpretationSpider
from gaokao_vault.spiders.major_satisfaction_spider import MajorSatisfactionSpider
from gaokao_vault.spiders.major_spider import MajorSpider
from gaokao_vault.spiders.school_major_spider import SchoolMajorSpider
from gaokao_vault.spiders.school_satisfaction_spider import SchoolSatisfactionSpider
from gaokao_vault.spiders.school_spider import SchoolSpider
from gaokao_vault.spiders.score_line_spider import ScoreLineSpider
from gaokao_vault.spiders.score_segment_spider import ScoreSegmentSpider
from gaokao_vault.spiders.special_spider import SpecialSpider
from gaokao_vault.spiders.timeline_spider import TimelineSpider

logger = logging.getLogger(__name__)


def _is_checkpoint_error(exc: BaseException) -> bool:
    """Check if an exception is a non-fatal checkpoint serialization/file error."""
    if hasattr(exc, "exceptions"):  # ExceptionGroup
        return all(_is_checkpoint_error(e) for e in exc.exceptions)  # ty: ignore[not-iterable]
    msg = str(exc).lower()
    if isinstance(exc, AttributeError) and ("pickle" in msg or "can't get local object" in msg):
        return True
    return isinstance(exc, (FileNotFoundError, OSError)) and "checkpoint" in msg


SPIDER_MAP: dict[str, type[BaseGaokaoSpider]] = {
    TaskType.SCHOOLS: SchoolSpider,
    TaskType.MAJORS: MajorSpider,
    TaskType.SCORE_LINES: ScoreLineSpider,
    TaskType.TIMELINES: TimelineSpider,
    TaskType.SCHOOL_MAJORS: SchoolMajorSpider,
    TaskType.SCORE_SEGMENTS: ScoreSegmentSpider,
    TaskType.ENROLLMENT_PLANS: EnrollmentPlanSpider,
    TaskType.CHARTERS: CharterSpider,
    TaskType.SPECIAL: SpecialSpider,
    TaskType.SCHOOL_SATISFACTION: SchoolSatisfactionSpider,
    TaskType.MAJOR_SATISFACTION: MajorSatisfactionSpider,
    TaskType.INTERPRETATIONS: InterpretationSpider,
}


class Orchestrator:
    """Three-phase crawl orchestrator.

    Phase 1: Dimension seeds (provinces, subject_categories) — handled by DB migration.
    Phase 2: Core entities (schools, majors, score_lines, timelines) — parallel.
    Phase 3: Associations (school_majors, score_segments, etc.) — parallel, depends on Phase 2.
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        config: CrawlConfig | None = None,
        mode: str = "full",
        db_config: DatabaseConfig | None = None,
        app_config: AppConfig | None = None,
    ):
        self.db_pool = db_pool  # Keep for TaskManager (main-loop operations)
        self.config = config or CrawlConfig()
        self.mode = mode
        self.db_config = db_config or DatabaseConfig()
        self._app_config = app_config
        self.task_manager = TaskManager(db_pool)

    async def run_all(self) -> None:
        logger.info("Starting full crawl orchestration (mode=%s)", self.mode)

        logger.info("=== Phase 2: Core entities ===")
        p2_results = await self._run_phase([t.value for t in PHASE2_TYPES])
        if not self._phase_results_are_stable(p2_results):
            failed = (
                0
                if p2_results is None
                else sum(
                    1
                    for r in p2_results
                    if isinstance(r, Exception) or (isinstance(r, dict) and r.get("failed", 0) > 0)
                )
            )
            logger.warning(
                "Skipping Phase 3 because Phase 2 is not stable (failed=%d total=%s)",
                failed,
                0 if p2_results is None else len(p2_results),
            )
            return

        logger.info("=== Phase 3: Associations ===")
        await self._run_phase([t.value for t in PHASE3_TYPES])

        logger.info("Crawl orchestration complete")

    async def run_types(self, types: list[str]) -> None:
        logger.info("Running selected types: %s", types)
        await self._run_phase(types)

    async def run_single(self, task_type: str) -> dict[str, int]:
        spider_cls = SPIDER_MAP.get(task_type)
        if spider_cls is None:
            logger.error("Unknown task type: %s", task_type)
            return {"failed": 1}

        task_id = await self.task_manager.start_task(task_type, {"mode": self.mode})
        timeout = self.config.spider_timeout

        try:
            spider = spider_cls(
                db_config=self.db_config,
                crawl_task_id=task_id,
                mode=self.mode,
                config=self.config,
                app_config=self._app_config,
                crawldir=os.path.join(self.config.crawl_dir, task_type),
            )
        except Exception as exc:
            logger.exception("Spider %s construction failed", task_type)
            stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 1}
            await self.task_manager.finish_task(task_id, stats, error=str(exc))
            return stats

        try:
            logger.info("Starting spider %s (timeout=%ds)", task_type, timeout)
            # Use spider.stream() — a native async interface that runs in the
            # current event loop.  On timeout spider.pause() gracefully shuts
            # down the crawl (saves checkpoint, closes browser sessions).
            await asyncio.wait_for(
                self._run_spider_stream(spider),
                timeout=timeout,
            )
            stats = spider._stats
            items_scraped = stats.get("new", 0) + stats.get("updated", 0)
            logger.info(
                "Spider %s completed items_scraped=%d",
                task_type,
                items_scraped,
            )
        except asyncio.TimeoutError:
            logger.warning("Spider %s timed out after %ds, calling pause()", task_type, timeout)
            spider.pause()
            stats = spider._stats
            stats["failed"] = max(stats.get("failed", 0), 1)
            await self.task_manager.finish_task(task_id, stats, error=f"Timed out after {timeout}s")
            return stats
        except Exception as exc:
            logger.exception("Spider %s failed", task_type)
            stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 1}
            await self.task_manager.finish_task(task_id, stats, error=str(exc))
            return stats
        else:
            await self.task_manager.finish_task(task_id, stats)
            return stats

    @staticmethod
    async def _run_spider_stream(spider) -> None:
        """Consume spider.stream() to drive the crawl in the current event loop."""
        try:
            async for _item in spider.stream():
                pass  # items are processed in spider callbacks via process_item
        except Exception as eg:
            if not hasattr(eg, "split"):
                raise
            checkpoint_errors, other_errors = eg.split(_is_checkpoint_error)  # ty: ignore[call-non-callable]
            if checkpoint_errors:
                logger.warning(
                    "Ignoring %d checkpoint error(s) in spider %s: %s",
                    len(checkpoint_errors.exceptions),
                    spider.name,
                    checkpoint_errors,
                )
            if other_errors:
                raise other_errors from None

    @staticmethod
    def _phase_results_are_stable(results: list | None) -> bool:
        if results is None:
            return False
        return all(not isinstance(result, Exception) and result.get("failed", 0) == 0 for result in results)

    async def _run_phase(self, task_types: list[str]) -> list | None:
        valid_types = [t for t in task_types if t in SPIDER_MAP]
        if not valid_types:
            return None

        tasks = [self.run_single(t) for t in valid_types]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.config.phase_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Phase timed out after %ds. Types: %s", self.config.phase_timeout, valid_types)
            return None

        for task_type, result in zip(valid_types, results, strict=True):
            if isinstance(result, Exception):
                logger.error("Phase task %s failed: %s", task_type, result)
            else:
                logger.info("Phase task %s stats: %s", task_type, result)
        return results
