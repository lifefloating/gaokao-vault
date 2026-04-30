from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from gaokao_vault.db.queries.admission import upsert_major_admission_result


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 88}


def test_upsert_major_admission_result_uses_natural_key() -> None:
    conn = _FakeConnection()

    admission_id = asyncio.run(
        upsert_major_admission_result(
            cast(Any, conn),
            {
                "school_id": 1,
                "major_id": 2,
                "province_id": 7,
                "year": 2025,
                "subject_category_id": 3,
                "batch": "本科批",
                "batch_code": "regular",
                "batch_category": "普通批",
                "batch_segment": None,
                "program_type": None,
                "eligibility_requirements": None,
                "plan_count": 9,
                "physical_exam_or_political_review": None,
                "political_review_requirement": None,
                "service_obligation": None,
                "school_code_raw": "10200",
                "school_name_raw": "测试大学",
                "major_group_code": "01",
                "major_code_raw": "080901",
                "campus": "主校区",
                "data_source": "gaokao.chsi.com.cn",
                "quality_flags": [],
            },
        )
    )

    assert admission_id == 88
    assert "major_admission_results" in conn.query
    assert "ON CONFLICT (school_id, major_id, province_id, year, subject_category_id, batch)" in conn.query
    assert "major_group_code" in conn.query
    assert "batch_code" in conn.query
    assert "batch_category" in conn.query
    assert "program_type" in conn.query
    assert "plan_count" in conn.query
    assert "physical_exam_or_political_review" in conn.query
    assert "political_review_requirement" in conn.query
    assert "10200" in conn.args
    assert "regular" in conn.args
    assert "普通批" in conn.args
    assert "080901" in conn.args
    assert json.dumps([], ensure_ascii=False) in conn.args
