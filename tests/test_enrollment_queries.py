from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from gaokao_vault.db.queries.enrollment import upsert_enrollment_plan


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 77}


def test_upsert_enrollment_plan_preserves_rule_and_quality_fields() -> None:
    conn = _FakeConnection()

    plan_id = asyncio.run(
        upsert_enrollment_plan(
            cast(Any, conn),
            {
                "school_id": 1,
                "province_id": 7,
                "year": 2025,
                "subject_category_id": 3,
                "batch": "本科批",
                "major_name": "计算机科学与技术",
                "major_group_code": "01",
                "major_code_raw": "080901",
                "campus": "主校区",
                "education_location": "长春市",
                "selection_requirement": "物理+化学",
                "physical_exam_limit": "不招色盲",
                "single_subject_limit": "英语单科不低于110分",
                "adjustment_rule": "服从专业调剂",
                "data_source": "gaokao.chsi.com.cn",
                "quality_flags": [],
            },
        )
    )

    assert plan_id == 77
    assert "enrollment_plans" in conn.query
    assert "major_group_code" in conn.query
    assert "selection_requirement" in conn.query
    assert "01" in conn.args
    assert "物理+化学" in conn.args
    assert json.dumps([], ensure_ascii=False) in conn.args
