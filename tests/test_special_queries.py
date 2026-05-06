from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from gaokao_vault.db.queries.special import upsert_special_enrollment


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 66}


def test_upsert_special_enrollment_preserves_strong_base_fields() -> None:
    conn = _FakeConnection()

    special_id = asyncio.run(
        upsert_special_enrollment(
            cast(Any, conn),
            {
                "enrollment_type": "强基计划",
                "special_admission_type": "strong_foundation",
                "province_code": "11",
                "school_code_raw": "10001",
                "school_name_raw": "测试大学",
                "year": 2025,
                "title": "测试大学2025年强基计划招生简章",
                "content_text": "报名时间: 2025年4月10日至2025年4月30日.",
                "source_section": "charter",
                "detail_url": "https://bm.chsi.com.cn/jcxkzs/sch/10001",
                "application_url": "https://bm.chsi.com.cn/jcxkzs/sch/10001",
                "registration_window": {"start": "2025-04-10", "end": "2025-04-30"},
                "registration_start": "2025-04-10",
                "registration_end": "2025-04-30",
                "milestones": {"registration_start": "2025-04-10", "registration_end": "2025-04-30"},
                "shortlist_rule": "按高考成绩确定入围名单",
                "selection_rule": "按高考成绩确定入围名单",
                "school_assessment": "学校考核包括笔试和面试",
                "school_exam_rule": "学校考核包括笔试和面试",
                "composite_score_formula": "综合成绩=高考成绩*85%+校测成绩*15%",
                "admission_rule": "按综合成绩择优录取",
                "eligible_majors": ["数学类", "物理学类"],
                "quality_flags": [],
            },
        )
    )

    assert special_id == 66
    assert "special_enrollments" in conn.query
    assert "special_admission_type" in conn.query
    assert "content_text" in conn.query
    assert "province_code" in conn.query
    assert "school_code_raw" in conn.query
    assert "school_name_raw" in conn.query
    assert "source_section" in conn.query
    assert "detail_url" in conn.query
    assert "registration_window" in conn.query
    assert "milestones" in conn.query
    assert "shortlist_rule" in conn.query
    assert "school_assessment" in conn.query
    assert "application_url" in conn.query
    assert "school_exam_rule" in conn.query
    assert "composite_score_formula" in conn.query
    assert "eligible_majors" in conn.query
    assert "strong_foundation" in conn.args
    assert "报名时间: 2025年4月10日至2025年4月30日." in conn.args
    assert "11" in conn.args
    assert "10001" in conn.args
    assert "测试大学" in conn.args
    assert "charter" in conn.args
    assert json.dumps({"start": "2025-04-10", "end": "2025-04-30"}, ensure_ascii=False) in conn.args
    assert (
        json.dumps({"registration_start": "2025-04-10", "registration_end": "2025-04-30"}, ensure_ascii=False)
        in conn.args
    )
    assert "https://bm.chsi.com.cn/jcxkzs/sch/10001" in conn.args
    assert json.dumps(["数学类", "物理学类"], ensure_ascii=False) in conn.args


def test_upsert_special_enrollment_uses_source_identity_for_chsi_rows() -> None:
    conn = _FakeConnection()

    asyncio.run(
        upsert_special_enrollment(
            cast(Any, conn),
            {
                "enrollment_type": "强基计划",
                "special_admission_type": "strong_foundation",
                "school_code_raw": "92002",
                "year": 2026,
                "title": "2026年强基计划录取标准",
                "source_section": "announcement",
                "detail_url": "https://bm.chsi.com.cn/jcxkzs/sch/viewggtz/92002/101",
            },
        )
    )

    assert "ON CONFLICT (enrollment_type, school_id, school_code_raw, year, title, source_section, detail_url)" in (
        conn.query
    )
