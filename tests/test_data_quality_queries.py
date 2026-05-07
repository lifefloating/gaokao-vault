from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, cast

from gaokao_vault.db.queries import data_quality
from gaokao_vault.db.queries.data_quality import (
    fetch_major_answer_readiness_gaps,
    fetch_major_answer_readiness_match_diagnostics,
    fetch_major_answer_readiness_summary,
    fetch_major_strength_signal_diagnostics,
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


def test_fetch_major_answer_readiness_gaps_checks_scores_plans_groups_selection_and_strength() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "province_name": "吉林",
            "plan_year": 2026,
            "school_name": "长春理工大学",
            "major_name": "光电信息科学与工程",
            "readiness_flags": ["missing_admission_min_score_rank"],
            "answer_ready": False,
        }
    ]

    rows = asyncio.run(
        fetch_major_answer_readiness_gaps(
            cast(Any, conn),
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
            limit=20,
        )
    )

    assert rows == conn.rows
    assert "enrollment_plans" in conn.query
    assert "major_admission_results" in conn.query
    assert "school_major_strength_signals" in conn.query
    assert "school_majors" in conn.query
    assert "min_score IS NOT NULL" in conn.query
    assert "min_rank IS NOT NULL" in conn.query
    assert "max_score" in conn.query
    assert "avg_score" in conn.query
    assert "admitted_count" in conn.query
    assert "plan_count" in conn.query
    assert "major_group_code" in conn.query
    assert "major_code_raw" in conn.query
    assert "selection_requirement" in conn.query
    assert "ep.id AS enrollment_plan_id" in conn.query
    assert "BOOL_OR(ep.major_group_code IS NOT NULL)" not in conn.query
    assert "BOOL_OR(ep.major_code_raw IS NOT NULL)" not in conn.query
    assert "BOOL_OR(ep.selection_requirement IS NOT NULL)" not in conn.query
    assert "missing_plan_count" in conn.query
    assert "missing_major_group_code" in conn.query
    assert "missing_major_code_raw" in conn.query
    assert "missing_selection_requirement" in conn.query
    assert "missing_admission_min_score" in conn.query
    assert "missing_admission_min_rank" in conn.query
    assert "missing_admission_linkage" in conn.query
    assert "admission_match_type" in conn.query
    assert "admission_by_normalized_name" in conn.query
    assert "latest_min_score" in conn.query
    assert "latest_min_score_year" in conn.query
    assert "latest_min_rank" in conn.query
    assert "latest_min_rank_year" in conn.query
    assert "MAX(mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS latest_min_score_year" in conn.query
    assert "MAX(mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS latest_min_rank_year" in conn.query
    assert "latest_admission_year" not in conn.query
    assert "missing_strength_evidence" in conn.query
    assert "CARDINALITY($3::INTEGER[])" in conn.query
    assert "WHERE NOT answer_ready" in conn.query
    assert "INSERT" not in conn.query.upper()
    assert "UPDATE" not in conn.query.upper()
    assert "DELETE" not in conn.query.upper()
    assert conn.args == ("吉林", 2026, [2023, 2024, 2025], 3, "本科批", 20)


def test_fetch_major_answer_readiness_summary_counts_scope_and_gap_flags() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "plan_major_count": 0,
            "answer_ready_count": 0,
            "gap_count": 0,
            "missing_plan_count": 0,
            "missing_major_group_code": 0,
            "missing_major_code_raw": 0,
            "missing_selection_requirement": 0,
            "missing_admission_min_score": 0,
            "missing_admission_min_rank": 0,
            "missing_admission_linkage": 0,
            "missing_strength_evidence": 0,
        }
    ]

    summary = asyncio.run(
        fetch_major_answer_readiness_summary(
            cast(Any, conn),
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
    )

    assert summary == conn.rows[0]
    assert "enrollment_plans" in conn.query
    assert "major_admission_results" in conn.query
    assert "school_major_strength_signals" in conn.query
    assert "COUNT(*)::INTEGER AS plan_major_count" in conn.query
    assert "CARDINALITY(readiness_flags) = 0" in conn.query
    assert "CARDINALITY(readiness_flags) > 0" in conn.query
    assert "'missing_plan_count' = ANY(readiness_flags)" in conn.query
    assert "'missing_major_group_code' = ANY(readiness_flags)" in conn.query
    assert "'missing_major_code_raw' = ANY(readiness_flags)" in conn.query
    assert "'missing_selection_requirement' = ANY(readiness_flags)" in conn.query
    assert "'missing_admission_min_score' = ANY(readiness_flags)" in conn.query
    assert "'missing_admission_min_rank' = ANY(readiness_flags)" in conn.query
    assert "'missing_admission_linkage' = ANY(readiness_flags)" in conn.query
    assert "COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_score IS NOT NULL)" in conn.query
    assert "COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_rank IS NOT NULL)" in conn.query
    assert "'missing_strength_evidence' = ANY(readiness_flags)" in conn.query
    assert "LIMIT $6" not in conn.query
    assert "INSERT" not in conn.query.upper()
    assert "UPDATE" not in conn.query.upper()
    assert "DELETE" not in conn.query.upper()
    assert conn.args == ("吉林", 2026, [2023, 2024, 2025], 3, "本科批")


def test_fetch_major_answer_readiness_match_diagnostics_compares_exact_and_normalized_name_matches() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "plan_major_count": 5087,
            "plan_major_with_major_id_count": 4900,
            "exact_major_id_match_count": 155,
            "exact_major_id_match_with_min_score_count": 150,
            "exact_major_id_match_with_min_rank_count": 100,
            "normalized_name_match_count": 420,
            "normalized_name_match_with_min_score_count": 390,
            "normalized_name_match_with_min_rank_count": 250,
            "normalized_name_only_match_count": 265,
            "normalized_name_only_match_with_min_score_count": 240,
            "normalized_name_only_match_with_min_rank_count": 150,
            "unmatched_plan_major_count": 4667,
        }
    ]

    diagnostics = asyncio.run(
        fetch_major_answer_readiness_match_diagnostics(
            cast(Any, conn),
            province="吉林",
            plan_year=2025,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
    )

    assert diagnostics == conn.rows[0]
    assert "target_plans" in conn.query
    assert "admission_records" in conn.query
    assert "exact_matches" in conn.query
    assert "normalized_name_matches" in conn.query
    assert "exact_major_id_match_with_min_score_count" in conn.query
    assert "exact_major_id_match_with_min_rank_count" in conn.query
    assert "normalized_name_match_with_min_score_count" in conn.query
    assert "normalized_name_match_with_min_rank_count" in conn.query
    assert "normalized_name_only_match_count" in conn.query
    assert "normalized_name_only_match_with_min_score_count" in conn.query
    assert "normalized_name_only_match_with_min_rank_count" in conn.query
    assert "REGEXP_REPLACE" in conn.query
    assert "COALESCE(mar.major_name_raw, adm_major.name)" in conn.query
    assert "mar.min_score IS NOT NULL" in conn.query
    assert "mar.min_rank IS NOT NULL" in conn.query
    assert "INSERT" not in conn.query.upper()
    assert "UPDATE" not in conn.query.upper()
    assert "DELETE" not in conn.query.upper()
    assert conn.args == ("吉林", 2025, [2023, 2024, 2025], 3, "本科批")


def test_major_answer_readiness_match_diagnostics_does_not_group_unaggregated_normalized_names() -> None:
    conn = _FakeConnection()

    asyncio.run(
        fetch_major_answer_readiness_match_diagnostics(
            cast(Any, conn),
            province="吉林",
            plan_year=2025,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
    )

    target_plans_sql = conn.query.split("target_plans AS (", 1)[1].split("),\n        admission_records AS", 1)[0]
    admission_records_sql = conn.query.split("admission_records AS (", 1)[1].split("),\n        exact_matches AS", 1)[0]

    assert "GROUP BY ep.school_id, ep.major_id, COALESCE(plan_major.name, ep.major_name)" not in target_plans_sql
    assert "GROUP BY\n                mar.school_id" not in admission_records_sql


def test_major_answer_readiness_queries_share_one_normalized_major_name_sql_fragment() -> None:
    conn = _FakeConnection()

    asyncio.run(
        fetch_major_answer_readiness_gaps(
            cast(Any, conn),
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
    )

    readiness_query = conn.query
    asyncio.run(
        fetch_major_answer_readiness_match_diagnostics(
            cast(Any, conn),
            province="吉林",
            plan_year=2025,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
    )

    plan_expression = data_quality._normalized_major_name_sql("COALESCE(plan_major.name, ep.major_name, '')")
    admission_expression = data_quality._normalized_major_name_sql("COALESCE(mar.major_name_raw, adm_major.name, '')")

    assert plan_expression in readiness_query
    assert admission_expression in readiness_query
    assert plan_expression in conn.query
    assert admission_expression in conn.query


def test_fetch_major_strength_signal_diagnostics_counts_signal_and_rollup_coverage() -> None:
    conn = _FakeConnection()
    conn.rows = [
        {
            "plan_major_count": 5087,
            "plan_major_with_school_major_count": 5000,
            "plan_major_with_strength_signal_count": 120,
            "plan_major_with_strength_rollup_count": 80,
            "plan_major_signal_without_rollup_count": 40,
        }
    ]

    diagnostics = asyncio.run(
        fetch_major_strength_signal_diagnostics(
            cast(Any, conn),
            province="吉林",
            plan_year=2025,
            subject_category_id=3,
            batch="本科批",
        )
    )

    assert diagnostics == conn.rows[0]
    assert "school_major_strength_signals" in conn.query
    assert "school_majors" in conn.query
    assert "plan_major_with_strength_signal_count" in conn.query
    assert "plan_major_with_strength_rollup_count" in conn.query
    assert "plan_major_signal_without_rollup_count" in conn.query
    assert "INSERT" not in conn.query.upper()
    assert "UPDATE" not in conn.query.upper()
    assert "DELETE" not in conn.query.upper()
    assert conn.args == ("吉林", 2025, 3, "本科批")
