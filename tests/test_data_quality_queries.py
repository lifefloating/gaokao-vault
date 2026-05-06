from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, cast

from gaokao_vault.db.queries.data_quality import (
    fetch_school_year_plan_gaps,
    fetch_year_data_coverage,
    normalize_completeness_years,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.rows: list[dict[str, object]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.query = query
        self.args = args
        return self.rows


def test_normalize_completeness_years_defaults_to_recent_three_completed_years_before_december() -> None:
    assert normalize_completeness_years(None, today=date(2026, 5, 6)) == [2023, 2024, 2025]


def test_normalize_completeness_years_includes_current_year_from_december() -> None:
    assert normalize_completeness_years(None, today=date(2026, 12, 1)) == [2024, 2025, 2026]


def test_fetch_year_data_coverage_compares_admissions_and_plans_by_year() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "province_code": "22",
            "province_name": "吉林",
            "year": 2024,
            "admission_schools": 210,
            "plan_schools": 198,
        }
    ]

    rows = asyncio.run(fetch_year_data_coverage(cast(Any, conn), province="吉林", years=[2023, 2024, 2025]))

    assert rows == conn.rows
    assert "major_admission_results" in conn.query
    assert "enrollment_plans" in conn.query
    assert "COUNT(*) FILTER (WHERE mar.plan_count IS NOT NULL)" in conn.query
    assert "COUNT(*) FILTER (WHERE ep.plan_count IS NOT NULL)" in conn.query
    assert "COUNT(*) FILTER (WHERE ep.major_group_code IS NOT NULL)" in conn.query
    assert "COUNT(*) FILTER (WHERE ep.selection_requirement IS NOT NULL)" in conn.query
    assert "admission_records_with_major_group_code" in conn.query
    assert "plan_records_with_major_group_code" in conn.query
    assert "plan_records_with_selection_requirement" in conn.query
    assert "INSERT" not in conn.query.upper()
    assert "UPDATE" not in conn.query.upper()
    assert "DELETE" not in conn.query.upper()
    assert conn.args == ("吉林", [2023, 2024, 2025])


def test_fetch_school_year_plan_gaps_lists_admission_rows_without_plan_rows() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "province_code": "22",
            "province_name": "吉林",
            "year": 2024,
            "school_id": 123,
            "school_name": "长春工业大学",
            "admission_records": 42,
            "plan_records": 0,
        }
    ]

    rows = asyncio.run(
        fetch_school_year_plan_gaps(cast(Any, conn), province="吉林", years=[2023, 2024, 2025], limit=100)
    )

    assert rows == conn.rows
    assert "major_admission_results" in conn.query
    assert "enrollment_plans" in conn.query
    assert "LEFT JOIN plan_school_years" in conn.query
    assert "COALESCE(ps.plan_records, 0) = 0" in conn.query
    assert "admission_records_with_major_group_code" in conn.query
    assert "plan_records_with_major_group_code" in conn.query
    assert "plan_records_with_selection_requirement" in conn.query
    assert "LIMIT $3" in conn.query
    assert conn.args == ("吉林", [2023, 2024, 2025], 100)
