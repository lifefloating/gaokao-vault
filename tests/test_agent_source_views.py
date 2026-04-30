from __future__ import annotations

from pathlib import Path

SCHEMA_SQL = Path("src/gaokao_vault/db/schema.sql").read_text(encoding="utf-8").lower()


def test_schema_exposes_gaokao_agent_source_views() -> None:
    assert "create schema if not exists gaokao_source" in SCHEMA_SQL
    for view_name in (
        "schools_v",
        "majors_v",
        "admission_records_v",
        "province_rules_v",
        "score_rank_v",
    ):
        assert f"create or replace view gaokao_source.{view_name}" in SCHEMA_SQL


def test_admission_records_view_contains_major_level_evidence_columns() -> None:
    for column_name in (
        "province_code",
        "admission_year",
        "school_id",
        "major_id",
        "batch_code",
        "min_score",
        "min_rank",
        "plan_count",
        "major_notes",
        "major_group_code",
        "program_type",
        "eligibility_requirements",
        "physical_exam_or_political_review",
        "service_obligation",
        "source_url",
    ):
        assert column_name in SCHEMA_SQL
