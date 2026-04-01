from __future__ import annotations

import asyncio
import logging

import asyncpg

from gaokao_vault.config import CrawlConfig
from gaokao_vault.constants import PHASE2_TYPES, PHASE3_TYPES, TaskType
from gaokao_vault.scheduler.task_manager import TaskManager
from gaokao_vault.spiders.announcement_spider import AnnouncementSpider
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

SPIDER_MAP: dict[str, type[BaseGaokaoSpider]] = {
    TaskType.SCHOOLS: SchoolSpider,
    TaskType.MAJORS: MajorSpider,
    TaskType.SCORE_LINES: ScoreLineSpider,
    TaskType.TIMELINES: TimelineSpider,
    TaskType.ANNOUNCEMENTS: AnnouncementSpider,
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
    Phase 2: Core entities (schools, majors, score_lines, timelines, announcements) — parallel.
    Phase 3: Associations (school_majors, score_segments, etc.) — parallel, depends on Phase 2.
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        config: CrawlConfig | None = None,
        mode: str = "full",
    ):
        self.db_pool = db_pool
        self.config = config or CrawlConfig()
        self.mode = mode
        self.task_manager = TaskManager(db_pool)

    async def run_all(self) -> None:
        logger.info("Starting full crawl orchestration (mode=%s)", self.mode)

        logger.info("=== Phase 2: Core entities ===")
        await self._run_phase([t.value for t in PHASE2_TYPES])

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

        try:
            spider = spider_cls(
                db_pool=self.db_pool,
                crawl_task_id=task_id,
                mode=self.mode,
                config=self.config,
            )
            spider.start()
            stats = spider.stats
        except Exception as e:
            logger.exception("Spider %s failed", task_type)
            stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 1}
            await self.task_manager.finish_task(task_id, stats, error=str(e))
            return stats
        else:
            await self.task_manager.finish_task(task_id, stats)
            return stats

    async def _run_phase(self, task_types: list[str]) -> None:
        valid_types = [t for t in task_types if t in SPIDER_MAP]
        if not valid_types:
            return

        tasks = [self.run_single(t) for t in valid_types]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for task_type, result in zip(valid_types, results, strict=True):
            if isinstance(result, Exception):
                logger.error("Phase task %s failed: %s", task_type, result)
            else:
                logger.info("Phase task %s stats: %s", task_type, result)
