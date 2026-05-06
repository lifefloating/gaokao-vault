from __future__ import annotations

from pathlib import Path

SCHEMA_SQL = Path("src/gaokao_vault/db/schema.sql").read_text(encoding="utf-8").lower()


def test_schema_exposes_gaokao_agent_source_views() -> None:
    assert "create schema if not exists gaokao_source" in SCHEMA_SQL
    for view_name in (
        "schools_v",
        "majors_v",
        "admission_records_v",
        "special_enrollments_v",
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
        "school_major_rank",
        "is_featured_major",
        "program_type",
        "eligibility_requirements",
        "physical_exam_or_political_review",
        "service_obligation",
        "selection_requirement",
        "source_url",
    ):
        assert column_name in SCHEMA_SQL


def test_special_enrollments_view_contains_strong_foundation_fields() -> None:
    for column_name in (
        "document_uid",
        "document_type",
        "special_admission_type",
        "school_code_raw",
        "school_name_raw",
        "source_section",
        "detail_url",
        "application_url",
        "registration_window",
        "milestones",
        "selection_rule",
        "school_assessment",
        "composite_score_formula",
        "admission_rule",
        "eligible_majors",
    ):
        assert column_name in SCHEMA_SQL


def test_majors_view_falls_back_to_major_category_when_subcategory_is_missing() -> None:
    assert (
        "alter table majors add column if not exists category_id integer references major_categories(id)" in SCHEMA_SQL
    )
    assert "left join major_categories mc on mc.id = coalesce(ms.category_id, m.category_id)" in SCHEMA_SQL
