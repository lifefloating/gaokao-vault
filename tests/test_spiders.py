"""Tests for spider imports and basic structure."""

from __future__ import annotations

from gaokao_vault.constants import TaskType
from gaokao_vault.scheduler.orchestrator import SPIDER_MAP
from gaokao_vault.spiders import (
    AnnouncementSpider,
    BaseGaokaoSpider,
    CharterSpider,
    EnrollmentPlanSpider,
    InterpretationSpider,
    MajorSatisfactionSpider,
    MajorSpider,
    SchoolMajorSpider,
    SchoolSatisfactionSpider,
    SchoolSpider,
    ScoreLineSpider,
    ScoreSegmentSpider,
    SpecialSpider,
    TimelineSpider,
)


class TestSpiderStructure:
    def test_all_spiders_have_name(self):
        spiders = [
            SchoolSpider,
            MajorSpider,
            ScoreLineSpider,
            TimelineSpider,
            AnnouncementSpider,
            SchoolMajorSpider,
            ScoreSegmentSpider,
            EnrollmentPlanSpider,
            CharterSpider,
            SpecialSpider,
            SchoolSatisfactionSpider,
            MajorSatisfactionSpider,
            InterpretationSpider,
        ]
        for cls in spiders:
            assert hasattr(cls, "name"), f"{cls.__name__} missing 'name'"
            assert cls.name != "base", f"{cls.__name__} still has base name"

    def test_all_spiders_have_task_type(self):
        spiders = [
            SchoolSpider,
            MajorSpider,
            ScoreLineSpider,
            TimelineSpider,
            AnnouncementSpider,
        ]
        for cls in spiders:
            assert hasattr(cls, "task_type"), f"{cls.__name__} missing 'task_type'"
            assert cls.task_type != "", f"{cls.__name__} has empty task_type"

    def test_spider_inherits_base(self):
        assert issubclass(SchoolSpider, BaseGaokaoSpider)
        assert issubclass(MajorSpider, BaseGaokaoSpider)
        assert issubclass(AnnouncementSpider, BaseGaokaoSpider)

    def test_spider_map_complete(self):
        expected_types = {t.value for t in TaskType if t not in (TaskType.MAJOR_CATEGORIES,)}
        mapped_types = set(SPIDER_MAP.keys())
        assert mapped_types == expected_types, f"Missing: {expected_types - mapped_types}"
