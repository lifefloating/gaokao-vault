from gaokao_vault.db.queries.crawl_meta import create_task, find_latest_hash, insert_snapshot, update_task_stats
from gaokao_vault.db.queries.enrollment import upsert_charter, upsert_enrollment_plan, upsert_timeline
from gaokao_vault.db.queries.majors import (
    upsert_major,
    upsert_major_category,
    upsert_major_interpretation,
    upsert_major_satisfaction,
    upsert_major_subcategory,
    upsert_school_major,
)
from gaokao_vault.db.queries.schools import find_school_by_sch_id, upsert_school, upsert_school_satisfaction
from gaokao_vault.db.queries.scores import batch_upsert_score_segments, upsert_score_line
from gaokao_vault.db.queries.special import upsert_special_enrollment

__all__ = [
    "batch_upsert_score_segments",
    "create_task",
    "find_latest_hash",
    "find_school_by_sch_id",
    "insert_snapshot",
    "update_task_stats",
    "upsert_charter",
    "upsert_enrollment_plan",
    "upsert_major",
    "upsert_major_category",
    "upsert_major_interpretation",
    "upsert_major_satisfaction",
    "upsert_major_subcategory",
    "upsert_school",
    "upsert_school_major",
    "upsert_school_satisfaction",
    "upsert_score_line",
    "upsert_special_enrollment",
    "upsert_timeline",
]
