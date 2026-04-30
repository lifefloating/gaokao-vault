from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.recommendation import find_candidate_admission_chain
from gaokao_vault.models.recommendation import CandidateProfile


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.rows: list[dict[str, object]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.query = query
        self.args = args
        return self.rows


def test_find_candidate_admission_chain_joins_profile_admissions_and_current_plan() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "school_id": 1,
            "school_name": "测试大学",
            "major_id": 2,
            "major_name": "计算机科学与技术",
            "admission_history": [{"year": 2025, "min_rank": 3456}],
            "current_plan_count": 5,
        }
    ]
    profile = CandidateProfile(
        province_id=7,
        year=2026,
        subject_category_id=3,
        score=612,
        rank=4000,
        batch="本科批",
        rank_window=1500,
        major_preferences=["计算机"],
        region_preferences=["吉林"],
        max_tuition=8000,
    )

    rows = asyncio.run(find_candidate_admission_chain(cast(Any, conn), profile))

    assert rows == conn.rows
    assert "major_admission_results" in conn.query
    assert "enrollment_plans" in conn.query
    assert "matched_candidates" in conn.query
    assert "current_plans" in conn.query
    assert "name_match_candidates" in conn.query
    assert "admission_history" in conn.query
    assert "current_plan_options" in conn.query
    assert "ep.major_id = mc.major_id OR ep.major_name = mc.major_name" not in conn.query
    assert "HAVING COUNT(DISTINCT major_id) = 1" in conn.query
    assert "ep.major_id IS NULL" in conn.query
    assert "ep.province_id = $1" in conn.query
    assert "ep.year = $2" in conn.query
    assert "ep.selection_requirement" in conn.query
    assert "major_group_code" in conn.query
    assert "min_rank" in conn.query
    assert "program_type" in conn.query
    assert "eligibility_requirements" in conn.query
    assert "physical_exam_or_political_review" in conn.query
    assert "service_obligation" in conn.query
    assert conn.args == (7, 2026, 3, "本科批", 2500, 5500, 4000, 3)
