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

__all__ = [
    "BaseGaokaoSpider",
    "CharterSpider",
    "EnrollmentPlanSpider",
    "InterpretationSpider",
    "MajorSatisfactionSpider",
    "MajorSpider",
    "SchoolMajorSpider",
    "SchoolSatisfactionSpider",
    "SchoolSpider",
    "ScoreLineSpider",
    "ScoreSegmentSpider",
    "SpecialSpider",
    "TimelineSpider",
]
