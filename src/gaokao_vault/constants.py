from __future__ import annotations

from enum import Enum

BASE_URL = "https://gaokao.chsi.com.cn"

META_FIELDS = frozenset({"id", "created_at", "updated_at", "crawl_task_id", "content_hash"})


class TaskType(str, Enum):
    SCHOOLS = "schools"
    SCHOOL_SATISFACTION = "school_satisfaction"
    MAJOR_CATEGORIES = "major_categories"
    MAJORS = "majors"
    SCHOOL_MAJORS = "school_majors"
    MAJOR_SATISFACTION = "major_satisfaction"
    INTERPRETATIONS = "interpretations"
    SCORE_LINES = "score_lines"
    SCORE_SEGMENTS = "score_segments"
    ENROLLMENT_PLANS = "enrollment_plans"
    CHARTERS = "charters"
    TIMELINES = "timelines"
    SPECIAL = "special"
    ANNOUNCEMENTS = "announcements"


PHASE2_TYPES = [
    TaskType.SCHOOLS,
    TaskType.MAJORS,
    TaskType.SCORE_LINES,
    TaskType.TIMELINES,
    TaskType.ANNOUNCEMENTS,
]

PHASE3_TYPES = [
    TaskType.SCHOOL_MAJORS,
    TaskType.SCORE_SEGMENTS,
    TaskType.ENROLLMENT_PLANS,
    TaskType.CHARTERS,
    TaskType.SPECIAL,
    TaskType.SCHOOL_SATISFACTION,
    TaskType.MAJOR_SATISFACTION,
    TaskType.INTERPRETATIONS,
]
